"""linux2mqtt helpers."""

import re


def sanitize(val: str) -> str:
    """Sanitize a value for unique_id usage.

    Parameters
    ----------
    val : str
        The string to sanitize

    Returns
    -------
    str
        The sanitized value

    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", val.lower())
