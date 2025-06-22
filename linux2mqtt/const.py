"""linux2mqtt const."""

import socket

from .type_definitions import Linux2MqttConfig

LOG_LEVEL_DEFAULT = "DEBUG"
HOMEASSISTANT_PREFIX_DEFAULT = "homeassistant"
MQTT_CLIENT_ID_DEFAULT = "linux2mqtt"
MQTT_PORT_DEFAULT = 1883
MQTT_TIMEOUT_DEFAULT = 30  # s
MQTT_TOPIC_PREFIX_DEFAULT = "linux"
MQTT_QOS_DEFAULT = 1
MAX_QUEUE_SIZE = 100
DEFAULT_INTERVAL = 30
MIN_INTERVAL = 5
MAX_INTERVAL = 86000
DEFAULT_NET_INTERVAL = 30
MIN_NET_INTERVAL = 5
MAX_NET_INTERVAL = 360
DEFAULT_CPU_INTERVAL = 30
MIN_CPU_INTERVAL = 5
MAX_CPU_INTERVAL = 360
DEFAULT_PACKAGE_INTERVAL = 3600
MIN_PACKAGE_INTERVAL = 300  # 5m
MAX_PACKAGE_INTERVAL = 86400  # 1d
DEFAULT_CONNECTIONS_INTERVAL = 10
MIN_CONNECTIONS_INTERVAL = 5
MAX_CONNECTIONS_INTERVAL = 360

DEFAULT_CONFIG = Linux2MqttConfig(
    {
        "log_level": LOG_LEVEL_DEFAULT,
        "homeassistant_prefix": HOMEASSISTANT_PREFIX_DEFAULT,
        "linux2mqtt_hostname": f"{socket.gethostname()}_{MQTT_CLIENT_ID_DEFAULT}",
        "mqtt_client_id": MQTT_CLIENT_ID_DEFAULT,
        "mqtt_user": "",
        "mqtt_password": "",
        "mqtt_host": "",
        "mqtt_port": MQTT_PORT_DEFAULT,
        "mqtt_timeout": MQTT_TIMEOUT_DEFAULT,
        "mqtt_topic_prefix": MQTT_TOPIC_PREFIX_DEFAULT,
        "mqtt_qos": MQTT_QOS_DEFAULT,
        "interval": DEFAULT_INTERVAL,
    }
)
