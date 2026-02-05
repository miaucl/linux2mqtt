#!/usr/bin/env python3
"""linux2mqtt class."""

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from os import geteuid, path
from pathlib import Path
import platform
from queue import Empty, Queue
import signal
import socket
import sys
from threading import Event
import time
from typing import Any
import uuid

import paho.mqtt.client
import paho.mqtt.enums
import psutil

from . import __version__
from .const import (
    DEFAULT_CONNECTIONS_INTERVAL,
    DEFAULT_CPU_INTERVAL,
    DEFAULT_INTERVAL,
    DEFAULT_NET_INTERVAL,
    DEFAULT_PACKAGE_INTERVAL,
    HOMEASSISTANT_DISABLE_ATTRIBUTES_DEFAULT,
    HOMEASSISTANT_PREFIX_DEFAULT,
    MAX_CONNECTIONS_INTERVAL,
    MAX_CPU_INTERVAL,
    MAX_INTERVAL,
    MAX_NET_INTERVAL,
    MAX_PACKAGE_INTERVAL,
    MAX_QUEUE_SIZE,
    MIN_CONNECTIONS_INTERVAL,
    MIN_CPU_INTERVAL,
    MIN_INTERVAL,
    MIN_NET_INTERVAL,
    MIN_PACKAGE_INTERVAL,
    MQTT_CLIENT_ID_DEFAULT,
    MQTT_PORT_DEFAULT,
    MQTT_QOS_DEFAULT,
    MQTT_TIMEOUT_DEFAULT,
)
from .exceptions import Linux2MqttConfigException, Linux2MqttConnectionException
from .helpers import clean_for_discovery, sanitize
from .metrics import (
    BaseMetric,
    CPUMetrics,
    DiskUsageMetrics,
    FanSpeedMetrics,
    NetConnectionMetrics,
    NetworkMetrics,
    PackageUpdateMetrics,
    TempMetrics,
    VirtualMemoryMetrics,
)
from .type_definitions import Linux2MqttConfig, LinuxDeviceEntry

main_logger = logging.getLogger("linux2mqtt")
mqtt_logger = logging.getLogger("linux2mqtt")


class Linux2Mqtt:
    """linux2mqtt class.

    Attributes
    ----------
    version
        The version of linux2mqtt
    cfg
        The config for linux2mqtt
    discovery_binary_sensor_topic
        Topic template for a binary sensor
    discovery_sensor_topic
        Topic template for a nary sensor
    status_topic
        Topic template for a status value
    version_topic
        Topic template for a version value
    state_topic
        Topic template for a state dict
    availability_topic
        Topic template for a availability value
    deferred_metrics_queue
        Queue with metrics to publish available through lazy gathering
    do_not_exit
        Prevent exit from within linux2mqtt, when handled outside

    """

    # Version
    version: str = __version__

    cfg: Linux2MqttConfig
    metrics: list[BaseMetric]
    first_connection_event: Event

    mqtt: paho.mqtt.client.Client

    discovery_binary_sensor_topic: str
    discovery_sensor_topic: str
    status_topic: str
    version_topic: str
    state_topic: str
    availability_topic: str

    deferred_metrics_queue: Queue[BaseMetric] = Queue(maxsize=MAX_QUEUE_SIZE)

    do_not_exit: bool

    def __init__(
        self,
        cfg: Linux2MqttConfig,
        do_not_exit: bool = True,
    ):
        """Initialize the linux2mqtt.

        Parameters
        ----------
        cfg
            The config for the linux2mqtt
        do_not_exit
            Prevent exit from within linux2mqtt, when handled outside

        Raises
        ------
        Linux2MqttConfigException
            Bad config

        """

        self.cfg = cfg
        self.do_not_exit = do_not_exit
        self.metrics = []
        self.first_connection_event = Event()

        system_name_sanitized = sanitize(self.cfg["linux2mqtt_hostname"])

        self.discovery_binary_sensor_topic = f"{self.cfg['homeassistant_prefix']}/binary_sensor/{self.cfg['mqtt_topic_prefix']}/{system_name_sanitized}_{{}}/config"
        self.discovery_sensor_topic = f"{self.cfg['homeassistant_prefix']}/sensor/{self.cfg['mqtt_topic_prefix']}/{system_name_sanitized}_{{}}/config"
        self.availability_topic = (
            f"{self.cfg['mqtt_topic_prefix']}/{system_name_sanitized}/{{}}/availability"
        )
        self.state_topic = (
            f"{self.cfg['mqtt_topic_prefix']}/{system_name_sanitized}/{{}}/state"
        )
        self.status_topic = (
            f"{self.cfg['mqtt_topic_prefix']}/{system_name_sanitized}/status"
        )
        self.version_topic = (
            f"{self.cfg['mqtt_topic_prefix']}/{system_name_sanitized}/version"
        )

        if not self.do_not_exit:
            main_logger.info("Register signal handlers for SIGINT and SIGTERM")
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)

        if self.cfg["interval"] < MIN_INTERVAL:
            raise Linux2MqttConfigException(
                "linux2mqtt could not start due to bad config"
            ) from ValueError(
                f"The interval for the mqtt update must at least {MIN_INTERVAL}s"
            )
        elif self.cfg["interval"] > MAX_INTERVAL:
            raise Linux2MqttConfigException(
                "linux2mqtt could not start due to bad config"
            ) from ValueError(
                f"The interval for the mqtt update must at most {MAX_INTERVAL}s"
            )

    def connect(self) -> None:
        """Initialize the linux2mqtt.

        Raises
        ------
        Linux2MqttConnectionException
            If anything with the mqtt connection goes wrong

        """
        try:
            self.mqtt = paho.mqtt.client.Client(
                callback_api_version=paho.mqtt.enums.CallbackAPIVersion.VERSION2,
                client_id=f"{self.cfg['mqtt_client_id']}_{uuid.uuid4().hex[:6]}",
            )
            self.mqtt.enable_logger(mqtt_logger)
            if self.cfg["mqtt_user"] or self.cfg["mqtt_password"]:
                self.mqtt.username_pw_set(
                    self.cfg["mqtt_user"], self.cfg["mqtt_password"]
                )
            self.mqtt.on_connect = self._on_connect
            self.mqtt.on_connect_fail = self._on_connect_fail
            self.mqtt.on_disconnect = self._on_disconnect
            self.mqtt.will_set(
                self.status_topic,
                "offline",
                qos=self.cfg["mqtt_qos"],
                retain=True,
            )
            self.mqtt.reconnect_delay_set(min_delay=1, max_delay=300)
            self.mqtt.connect_async(
                self.cfg["mqtt_host"], self.cfg["mqtt_port"], self.cfg["mqtt_timeout"]
            )
            self.mqtt.loop_start()
        except paho.mqtt.client.WebsocketConnectionError as ex:
            main_logger.exception("Error while trying to connect to MQTT broker.")
            main_logger.debug(ex)
            raise Linux2MqttConnectionException from ex

    def _report_all_statuses(self, status: bool) -> None:
        """Report linux2mqtt and metrics statuses on mqtt.

        Parameters
        ----------
        status
            The status to set on the status topic

        """
        for metric in self.metrics:
            self._report_status(
                self.availability_topic.format(metric.name_sanitized), status
            )
        self._report_status(self.status_topic, status)

    def _on_connect(
        self,
        _client: Any,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _props: Any = None,
    ) -> None:
        """Handle the connection return.

        Parameters
        ----------
        _client
            The client id (unused)
        _userdata
            The userdata (unused)
        _flags
            The flags (unused)
        reason_code
            The reason code
        _props
            The props (unused)

        """
        if reason_code == 0:
            main_logger.info("Connected to MQTT broker.")
            self._report_all_statuses(True)
            self._mqtt_send(self.version_topic, self.version, retain=True)
            self._create_discovery_topics()
            self.first_connection_event.set()
        else:
            main_logger.error("Connection refused : %s", reason_code.getName())

    def _on_connect_fail(self, _client: Any, _userdata: Any) -> None:
        """Handle the connection failure.

        Parameters
        ----------
        _client
            The client id (unused)
        _userdata
            The userdata (unused)

        """
        main_logger.error("Connect failed")

    def _on_disconnect(
        self,
        _client: Any,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _props: Any = None,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        """Handle the disconnection return.

        Parameters
        ----------
        _client
            The client id (unused)
        _userdata
            The userdata (unused)
        _flags
            The flags (unused)
        reason_code
            The reason code
        _props
            The props (unused)
        _args
            Any additional args
        _kwargs
            Any additional kwargs

        """
        # Case 1: clean disconnect or MQTT v5 reason code
        if hasattr(reason_code, "getName"):
            if reason_code == 0:
                main_logger.warning("Disconnected from MQTT broker.")
            else:
                main_logger.error(
                    "Disconnected: ReasonCode %s (%s)",
                    getattr(reason_code, "value", "n/a"),
                    reason_code.getName(),
                )

        # Case 2: connection refused / network failure
        else:
            main_logger.error(
                "Disconnected before CONNACK (likely auth or network issue): %s",
                reason_code,
            )

    def _mqtt_send(self, topic: str, payload: str, retain: bool = False) -> None:
        """Send a mqtt payload to for a topic.

        Parameters
        ----------
        topic
            The topic to send a payload to
        payload
            The payload to send to the topic
        retain
            Whether the payload should be retained by the mqtt server

        Raises
        ------
        Linux2MqttConnectionException
            If the mqtt client could not send the data

        """
        try:
            if main_logger.isEnabledFor(logging.DEBUG):
                main_logger.debug("Sending to MQTT: %s: %s", topic, payload)
            self.mqtt.publish(
                topic, payload=payload, qos=self.cfg["mqtt_qos"], retain=retain
            )

        except paho.mqtt.client.WebsocketConnectionError as ex:
            main_logger.exception("MQTT Publish Failed")
            main_logger.debug(ex)
            raise Linux2MqttConnectionException() from ex

    def _device_definition(self) -> LinuxDeviceEntry:
        """Create device definition of a container for each entity for home assistant.

        Returns
        -------
        LinuxDeviceEntry
            The device entry config

        """
        return {
            "identifiers": f"{sanitize(self.cfg['linux2mqtt_hostname'])}_{self.cfg['mqtt_topic_prefix']}",
            "name": f"{self.cfg['linux2mqtt_hostname']} {self.cfg['mqtt_topic_prefix'].title()}",
            "model": f"{platform.system()} {platform.machine()}",
            "hw_version": f"{platform.release()}",
            "sw_version": f"linux2mqtt {self.version}",
        }

    def _report_status(self, status_topic: str, status: bool) -> None:
        """Report a status on mqtt.

        Parameters
        ----------
        status_topic
            The status topic
        status
            The status to set on the status topic

        """
        self._mqtt_send(status_topic, "online" if status else "offline", retain=True)

    def __del__(self) -> None:
        """Destroy the class."""
        self._cleanup()

    def _signal_handler(self, _signum: Any, _frame: Any) -> None:
        """Handle a signal for SIGINT or SIGTERM on the process.

        Parameters
        ----------
        _signum
            (Unused)

        _frame
            (Unused)

        """
        self._cleanup()
        sys.exit(0)

    def _cleanup(self) -> None:
        """Cleanup the linux2mqtt."""
        main_logger.warning("Shutting down gracefully.")
        try:
            self._report_all_statuses(False)
            self.mqtt.loop_stop()
            self.mqtt.disconnect()
        except Linux2MqttConnectionException as ex:
            main_logger.exception("MQTT cleanup Failed")
            main_logger.debug(ex)
            main_logger.info("Ignoring cleanup error and exiting...")

    def _create_discovery_topics(self) -> None:
        """Create discovery topics for all metrics.

        Raises
        ------
        Linux2MqttConnectionException
            If anything with the mqtt connection goes wrong

        """
        for metric in self.metrics:
            discovery_entries = metric.get_discovery(
                self.state_topic,
                self.status_topic,
                self.availability_topic,
                self._device_definition(),
                self.cfg["homeassistant_disable_attributes"],
            )
            discovery_topic = (
                self.discovery_sensor_topic
                if metric.ha_sensor_type == "sensor"
                else self.discovery_binary_sensor_topic
            )
            for discovery_entry in discovery_entries:
                self._mqtt_send(
                    discovery_topic.format(sanitize(discovery_entry["name"])),
                    json.dumps(clean_for_discovery(discovery_entry)),
                    retain=True,
                )
            self._report_status(
                self.availability_topic.format(metric.name_sanitized), True
            )

    def add_metric(self, metric: BaseMetric) -> None:
        """Add metric to linux2mqtt.

        Parameters
        ----------
        metric
            The metric to add

        """
        self.metrics.append(metric)

    def _check_queue(self) -> None:
        """Check the queue of metrics for new data and publish it if present.

        Raises
        ------
        Linux2MqttConnectionException
            If anything with the mqtt connection goes wrong

        """
        while not self.deferred_metrics_queue.empty():
            try:
                queued_metric = self.deferred_metrics_queue.get()
                self._publish_metric(queued_metric)
            except Empty:
                pass

    def _publish_metric(self, metric: BaseMetric) -> None:
        """Check the queue of metrics for new data.

        Parameters
        ----------
        metric
            The metric to publish, containing new data in the .polled_result property

        Raises
        ------
        Linux2MqttConnectionException
            If anything with the mqtt connection goes wrong

        """
        r = metric.polled_result
        self._mqtt_send(
            self.state_topic.format(metric.name_sanitized), json.dumps(r), retain=False
        )

    def loop_busy(self, raise_known_exceptions: bool = False) -> None:
        """Monitor the metrics and handle the update interval for each metric.

        When not connected, it waits for it until the process is exited or a connection is established.

        Parameters
        ----------
        raise_known_exceptions
            Should any known processing exception be raised or ignored

        Raises
        ------
        Linux2MqttConnectionException
            If anything with the mqtt connection goes wrong

        """
        while not self.first_connection_event.wait(5):
            main_logger.debug("Waiting for connection.")

        while True:
            try:
                for metric in self.metrics:
                    is_deferred = metric.poll(result_queue=self.deferred_metrics_queue)
                    if not is_deferred:
                        self._publish_metric(metric)
            except Linux2MqttConnectionException as ex:
                if raise_known_exceptions:
                    raise ex  # noqa: TRY201
                else:
                    main_logger.warning(
                        "Do not raise due to raise_known_exceptions=False: %s", str(ex)
                    )
            x = 0
            while x < self.cfg["interval"]:
                # Check the queue for deferred results one/sec
                time.sleep(1)
                self._check_queue()
                x += 1


def configure_logger(
    logger: logging.Logger, verbosity: int, logdir: str | None
) -> None:
    """Configure main logger.

    Parameters
    ----------
    logger
        The logger to configure
    verbosity
        The verbosity level
    logdir
        The log directory

    """
    if verbosity >= 5:
        main_logger.setLevel(logging.DEBUG)
    elif verbosity == 4:
        main_logger.setLevel(logging.INFO)
    elif verbosity == 3:
        main_logger.setLevel(logging.WARNING)
    elif verbosity == 2:
        main_logger.setLevel(logging.ERROR)
    elif verbosity == 1:
        main_logger.setLevel(logging.CRITICAL)

    # Configure logger
    main_logger.propagate = False

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    main_logger.addHandler(console_handler)

    if logdir:
        try:
            logdirpath = Path(logdir)
            absolute_logdir = (
                logdirpath.resolve() if not logdirpath.is_absolute() else logdirpath
            )
            absolute_logdir.mkdir(parents=True, exist_ok=True)
            log_file = path.join(absolute_logdir, f"linux2mqtt-{logger.name}.log")
            file_handler = RotatingFileHandler(
                log_file, maxBytes=1_000_000, backupCount=5
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as ex:
            logger.warning(
                "Failed to initialize logging to directory %s : %s",
                logdir,
                str(ex),
            )


def main() -> None:
    """Run main entry for the linux2mqtt executable.

    Raises
    ------
    Linux2MqttConfigException
        Bad config
    Linux2MqttConnectionException
        If anything with the mqtt connection goes wrong

    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--name",
        default=socket.gethostname(),
        help="A descriptive name for the system being monitored (default: hostname)",
    )
    parser.add_argument(
        "--host",
        default="",
        help="Hostname or IP address of the MQTT broker (default: localhost)",
    )
    parser.add_argument(
        "--port",
        default=MQTT_PORT_DEFAULT,
        type=int,
        help="Port or IP address of the MQTT broker (default: 1883)",
    )
    parser.add_argument(
        "--client",
        default=f"{socket.gethostname()}_{MQTT_CLIENT_ID_DEFAULT}",
        help=f"Client Id for MQTT broker client (default: <hostname>_{MQTT_CLIENT_ID_DEFAULT})",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Username for MQTT broker authentication (default: None)",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Password for MQTT broker authentication (default: None)",
    )
    parser.add_argument(
        "--qos",
        default=MQTT_QOS_DEFAULT,
        type=int,
        help="QOS for standard MQTT messages (default: 1)",
        choices=range(0, 3),
    )
    parser.add_argument(
        "--timeout",
        default=MQTT_TIMEOUT_DEFAULT,
        type=int,
        help=f"The timeout for the MQTT connection. (default: {MQTT_TIMEOUT_DEFAULT}s)",
    )
    parser.add_argument(
        "--interval",
        default=DEFAULT_INTERVAL,
        type=int,
        help="Publish metrics to MQTT broker every n seconds (default: 30)",
        choices=range(MIN_INTERVAL, MAX_INTERVAL),
        metavar="INTERVAL",
    )
    parser.add_argument(
        "--homeassistant-prefix",
        default=HOMEASSISTANT_PREFIX_DEFAULT,
        help="MQTT discovery topic prefix (default: homeassistant)",
    )
    parser.add_argument(
        "--homeassistant-disable-attributes",
        nargs="?",
        type=bool,
        const=True,
        default=HOMEASSISTANT_DISABLE_ATTRIBUTES_DEFAULT,
        help="Disable homeassistant attributes and expose everything as entities (default: False)",
    )
    parser.add_argument(
        "--topic-prefix", default="linux", help="MQTT topic prefix (default: linux)"
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        action="count",
        default=0,
        help="Log verbosity (default: 0 (log output disabled))",
    )
    parser.add_argument(
        "--cpu",
        help="Publish CPU metrics",
        type=int,
        nargs="?",
        const=DEFAULT_CPU_INTERVAL,
        default=None,
        metavar="INTERVAL",
        choices=range(MIN_CPU_INTERVAL, MAX_CPU_INTERVAL),
    )
    parser.add_argument("--vm", help="Publish virtual memory", action="store_true")
    parser.add_argument(
        "--du",
        help="Publish disk usage metrics",
        type=str,
        action="append",
        nargs="?",
        const="/",
        default=None,
        metavar="MOUNT",
    )
    parser.add_argument(
        "--net",
        help=f"Publish network interface metrics. Specify the interface name and collection interval [{MIN_NET_INTERVAL},{MAX_NET_INTERVAL}] (default={DEFAULT_NET_INTERVAL}) separated by a comma",
        type=str,
        action="append",
        nargs="?",
        const="/",
        default=None,
        metavar="NIC",
    )
    parser.add_argument(
        "--connections",
        help="Publish network connections",
        type=int,
        nargs="?",
        const=DEFAULT_CONNECTIONS_INTERVAL,
        default=None,
        metavar="INTERVAL",
        choices=range(MIN_CONNECTIONS_INTERVAL, MAX_CONNECTIONS_INTERVAL),
    )
    parser.add_argument(
        "--temp", help="Publish temperature of thermal zones", action="store_true"
    )
    parser.add_argument("--fan", help="Publish fan speeds", action="store_true")
    parser.add_argument(
        "--packages",
        help="Publish package updates if available",
        type=int,
        nargs="?",
        const=DEFAULT_PACKAGE_INTERVAL,
        default=None,
        metavar="INTERVAL",
        choices=range(MIN_PACKAGE_INTERVAL, MAX_PACKAGE_INTERVAL),
    )
    parser.add_argument(
        "--logdir",
        default=None,
        help="Enables logging to specified directory (default: None)",
    )

    try:
        args = parser.parse_args()
    except argparse.ArgumentError as ex:
        raise Linux2MqttConfigException("Cannot start due to bad config") from ex
    except argparse.ArgumentTypeError as ex:
        raise Linux2MqttConfigException(
            "Cannot start due to bad config data type"
        ) from ex

    configure_logger(main_logger, args.verbosity, args.logdir)
    configure_logger(mqtt_logger, args.verbosity, args.logdir)

    log_level = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "DEBUG"][
        args.verbosity
    ]
    cfg = Linux2MqttConfig(
        {
            "log_level": log_level,
            "homeassistant_prefix": args.homeassistant_prefix,
            "homeassistant_disable_attributes": args.homeassistant_disable_attributes,
            "linux2mqtt_hostname": args.name,
            "mqtt_client_id": args.client,
            "mqtt_user": args.username,
            "mqtt_password": args.password,
            "mqtt_host": args.host,
            "mqtt_port": args.port,
            "mqtt_timeout": args.timeout,
            "mqtt_topic_prefix": args.topic_prefix,
            "mqtt_qos": args.qos,
            "interval": args.interval,
        }
    )

    stats = Linux2Mqtt(
        cfg,
        do_not_exit=False,
    )
    if args.cpu:
        cpu = CPUMetrics(interval=args.cpu)
        stats.add_metric(cpu)
    if args.vm:
        vm = VirtualMemoryMetrics()
        stats.add_metric(vm)

    if args.du:
        for mountpoint in args.du:
            du = DiskUsageMetrics(mountpoint=mountpoint)
            stats.add_metric(du)

    if args.connections:
        nc = NetConnectionMetrics(interval=args.connections)
        stats.add_metric(nc)

    if args.net:
        for nic in args.net:
            try:
                n, i = nic.split(",")
                i = int(i)
            except ValueError:
                n = nic
                i = 15
            net = NetworkMetrics(n, i)
            stats.add_metric(net)

    if args.temp:
        st = psutil.sensors_temperatures()
        for device in st:
            for idx, thermal_zone in enumerate(st[device]):
                tm = TempMetrics(device=device, idx=idx, label=thermal_zone.label)
                stats.add_metric(tm)

    if args.fan:
        fans = psutil.sensors_fans()
        for device in fans:
            for idx, fan in enumerate(fans[device]):
                fm = FanSpeedMetrics(device=device, idx=idx, label=fan.label)
                stats.add_metric(fm)

    if args.packages:
        package_updates = PackageUpdateMetrics(
            update_interval=args.packages, is_privileged=geteuid() == 0
        )
        stats.add_metric(package_updates)

    if not (
        args.vm
        or args.connections
        or args.cpu
        or args.du
        or args.net
        or args.temp
        or args.fan
        or args.packages
    ):
        main_logger.warning("No metrics specified. Nothing will be published.")

    stats.connect()
    stats.loop_busy()


if __name__ == "__main__":
    main()
