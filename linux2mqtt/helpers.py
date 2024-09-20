"""linux2mqtt helpers."""

import re

from .type_definitions import LinuxEntry


def sanitize(val: str) -> str:
    """Sanitize a value for unique_id usage.

    Parameters
    ----------
    val
        The string to sanitize

    Returns
    -------
    str
        The sanitized value

    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", val.lower())


def clean_for_discovery(val: LinuxEntry) -> dict[str, str | int | float | object]:
    """Cleanup a typed dict for home assistant discovery, which is quite picky and does not like empty of None values.

    Parameters
    ----------
    val
        The TypedDict to cleanup

    Returns
    -------
    dict
        The cleaned dict

    """

    return {
        k: v
        for k, v in dict(val).items()
        if isinstance(v, str | int | float | object) and v not in (None, "")
    }
