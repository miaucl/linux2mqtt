"""Package managers."""

from subprocess import DEVNULL, PIPE, STDOUT, Popen, run
from time import time

from .exceptions import (
    Linux2MqttException,
    NoPackageManagerFound,
    PackageManagerException,
)


class PackageManager:
    """Base class for all package managers to implement."""

    updates: list[str]
    update_interval: int
    is_privileged: bool
    has_sudo: bool
    last_updated: float | None

    def __init__(self, update_interval: int, is_privileged: bool):
        """Set up core properties shared across package managers.

        Parameters
        ----------
        update_interval
            How many seconds should elapse between updating
            package databases (such as `apt update`)

        is_privileged
            Indicates if the invoking user is privileged,
            used for some update operations where privilege is
            required

        """
        self.updates = []
        self.last_updated = None
        self.update_interval = update_interval
        self.is_privileged = is_privileged

        # If we're already privileged, don't bother
        # checking for sudo
        if is_privileged:
            self.has_sudo = False
        else:
            self.has_sudo = self.is_sudo_present()

    def _update(self) -> None:
        """Package manager specific update function."""
        raise Linux2MqttException from NotImplementedError

    def update_if_needed(self) -> None:
        """Run update commands if enough time has elapsed."""
        if (
            self.last_updated is None
            or (time() - self.last_updated) >= self.update_interval
        ):
            self.last_updated = time()
            self._update()

    def is_sudo_present(self) -> bool:
        """Check if this system has sudo utility present."""
        try:
            result = run(["sudo", "-h"], stdout=DEVNULL, stderr=STDOUT, check=False)
        except FileNotFoundError:
            return False
        return result.returncode == 0

    def run_privileged_command(self, args: list[str], required: bool) -> bool:
        """Run a command with elevated privileges."""
        # We're already effectively root
        if not self.is_privileged:
            if self.has_sudo:
                # If we have access to sudo, run it non interactively
                # this allows non privileged users to be configured via
                # sudoers to run specific commands (like apt update)
                args = ["sudo", "-n"] + args
            else:
                if required:
                    raise PackageManagerException(
                        "Required privileged command but lack privilege"
                    )

                return False

        # Update the cache to detect available updates
        res = run(args, stdout=DEVNULL, stderr=STDOUT, check=False)

        if res.returncode != 0 and required:
            raise PackageManagerException(
                "Required privileged command but lack privilege"
            )

        return res.returncode == 0

    @staticmethod
    def is_available() -> bool:
        """System check if a given package manager is available.

        Returns
        -------
        bool
            Showing if this specific type of Package Manager is
            available on this system

        """
        raise Linux2MqttException from NotImplementedError

    def get_available_updates(self) -> list[str]:
        """Gather list of packages with an update available.

        Returns
        -------
        list[str]
            Each package name which has an update available

        """
        raise Linux2MqttException from NotImplementedError


class Apk(PackageManager):
    """Package manager typically seen in Alpine Linux."""

    @staticmethod
    def is_available() -> bool:
        """Check if APK is available on this system."""
        try:
            result = run(["apk", "version"], stdout=DEVNULL, stderr=STDOUT, check=False)
        except FileNotFoundError:
            return False
        return result.returncode == 0

    def _update(self) -> None:
        """Apk specific update method."""
        self.run_privileged_command(["apk", "update"], True)

    def get_available_updates(self) -> list[str]:
        """Get packages available for update in APK."""
        self.updates = []
        with Popen(
            ["apk", "upgrade", "--no-interactive", "--simulate"],
            stdout=PIPE,
            stderr=DEVNULL,
            text=True,
        ) as proc:
            stdout, stderr = proc.communicate(timeout=30)

            if proc.returncode != 0:
                raise PackageManagerException(
                    f"Non zero simulated apk upgrade: {proc.returncode}: '{stderr}'"
                )

            for line in stdout.splitlines():
                line = line.strip()

                if not line:
                    continue

                if not line.startswith("("):
                    continue

                try:
                    _, package = line.split("Upgrading ", 1)
                    package, _ = package.split(" ", 1)
                    self.updates.append(package)
                except ValueError:
                    continue

        return self.updates


class Apt(PackageManager):
    """Package manager typically seen in Debian and Ubuntu based systems."""

    @staticmethod
    def is_available() -> bool:
        """Check if APT is available on this system."""
        try:
            # Can't even rely on `apt --version` being consistent,
            # mint has `apt version` instead.
            result = run(
                ["apt", "show", "apt"], stdout=DEVNULL, stderr=STDOUT, check=False
            )
        except FileNotFoundError:
            return False
        return result.returncode == 0

    def _update(self) -> None:
        # Opportunistically run privileged update
        # but dont attempt repeatedly if the first one fails
        self.run_privileged_command(["apt", "update"], required=False)

    def get_available_updates(self) -> list[str]:
        """Get packages available for update in APT."""
        self.updates = []
        with Popen(
            ["apt", "list", "--upgradeable"], stdout=PIPE, stderr=STDOUT, text=True
        ) as proc:
            stdout, _ = proc.communicate(timeout=30)

            if proc.returncode != 0:
                raise PackageManagerException(f"Non zero apt list: {proc.returncode}")

            for line in stdout.splitlines():
                line = line.strip()

                if not line:
                    continue

                if line.startswith("Listing") or line.startswith("WARNING"):
                    continue

                try:
                    package, _ = line.split(" ", 1)

                    if "/" in package:
                        package, _ = package.split("/", 1)
                    self.updates.append(package)
                except ValueError:
                    continue

        return self.updates


class Yum(PackageManager):
    """Package manager typically seen in Red Hat and CentOS based systems."""

    @staticmethod
    def is_available() -> bool:
        """Check if YUM is available on this system."""
        try:
            result = run(
                ["yum", "--version"], stdout=DEVNULL, stderr=STDOUT, check=False
            )
        except FileNotFoundError:
            return False
        return result.returncode == 0

    def _update(self) -> None:
        """Yum has no seperate update method."""
        pass

    def get_available_updates(self) -> list[str]:
        """Get packages available for update in YUM."""
        update_command = ["yum", "list", "updates", "--color", "0", "--quiet"]

        if self.has_sudo:
            update_command = ["sudo", "-n"] + update_command

        self.updates = []
        with Popen(update_command, stdout=PIPE, stderr=STDOUT, text=True) as proc:
            stdout, stderr = proc.communicate(timeout=30)

            if proc.returncode != 0:
                raise PackageManagerException(
                    f"Non zero yum list: {proc.returncode}: {stderr}"
                )

            for line in stdout.splitlines():
                line = line.strip()

                if not line:
                    continue

                if line.startswith("Available Upgrades"):
                    continue

                try:
                    package, _ = line.split(" ", 1)

                    if "." in package:
                        package, _ = package.split(".", 1)
                    self.updates.append(package)
                except ValueError:
                    continue

        return self.updates


def get_package_manager(update_interval: int, is_privileged: bool) -> PackageManager:
    """Determine which package manager is available.

    Returns
    -------
    PackageManager
        The specific package manager for this system

    Raises
    ------
    NoPackageManagerFound
        If no available package manager is found

    """
    for manager in (
        Apk,
        Apt,
        Yum,
    ):
        if manager.is_available():
            return manager(update_interval, is_privileged)

    raise NoPackageManagerFound()
