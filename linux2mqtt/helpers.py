"""linux2mqtt helpers."""


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
    return val.lower().replace(" ", "_").replace("/", "_")
