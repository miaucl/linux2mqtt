"""linux2mqtt exceptions."""


class Linux2MqttException(Exception):
    """General processing exception occurred."""


class Linux2MqttConfigException(Linux2MqttException):
    """Bad config exception occurred."""


class Linux2MqttConnectionException(Linux2MqttException):
    """Connection processing exception occurred."""


class Linux2MqttMetricsException(Linux2MqttException):
    """Metrics processing exception occurred."""


class NoPackageManagerFound(Linux2MqttException):
    """No package manager is identified for this system."""


class PackageManagerException(Linux2MqttException):
    """Generic package manager exception occurred."""
