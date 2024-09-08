"""linux2mqtt helpers."""

from urllib.parse import quote


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
    return quote(val)
