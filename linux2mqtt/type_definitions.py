"""linux2mqtt type definitions."""

from typing import Literal, TypedDict

StatusType = Literal["online", "offline"]
"""Metric status"""

SensorType = Literal["sensor", "binary_sensor"]
"""Sensor type for discovery"""


class Linux2MqttConfig(TypedDict):
    """A config object.

    Attributes
    ----------
    log_level
        Log verbosity
    homeassistant_prefix
        MQTT discovery topic prefix
    linux2mqtt_hostname
        A descriptive name for the system being monitored
    mqtt_client_id
        Client Id for MQTT broker client
    mqtt_user
        Username for MQTT broker authentication
    mqtt_password
        Password for MQTT broker authentication
    mqtt_host
        Hostname or IP address of the MQTT broker
    mqtt_port
        Port or IP address of the MQTT broker
    mqtt_timeout
        Timeout for MQTT messages
    mqtt_topic_prefix
        MQTT topic prefix
    mqtt_qos
        QOS for standard MQTT messages
    interval
        Publish metrics to MQTT broker every n seconds

    """

    log_level: str
    homeassistant_prefix: str
    linux2mqtt_hostname: str
    mqtt_client_id: str
    mqtt_user: str
    mqtt_password: str
    mqtt_host: str
    mqtt_port: int
    mqtt_timeout: int
    mqtt_topic_prefix: str
    mqtt_qos: int
    interval: int


class LinuxDeviceEntry(TypedDict):
    """A linux device entry object for discovery in home assistant.

    Attributes
    ----------
    identifiers
        A unique str to identify the device in home assistant
    name
        The name of the device to display in home assistant
    model
        The model of the device as additional info

    """

    identifiers: str
    name: str
    model: str


class LinuxEntry(TypedDict):
    """A linux entry object for discovery in home assistant.

    Attributes
    ----------
    name
        The name of the sensor to display in home assistant
    unique_id
        The unique id of the sensor in home assistant
    icon
        The icon of the sensor to display
    availability_topic
        The topic to check the availability of the sensor
    payload_available
        The payload of availability_topic of the sensor when available
    payload_unavailable
        The payload of availability_topic of the sensor when unavailable
    state_topic
        The topic containing all information for the state of the sensor
    value_template
        The jinja2 template to extract the state value from the state_topic for the sensor
    unit_of_measurement
        The unit of measurement of the sensor
    payload_on
        When a binary sensor: The value of extracted state of the sensor to be considered 'on'
    payload_off
        When a binary sensor: The value of extracted state of the sensor to be considered 'off'
    device
        The device the sensor is attributed to
    device_class
        The device class of the sensor
    state_topic
        The topic containing all information for the attributes of the sensor
    qos
        The QOS of the discovery message

    """

    name: str
    unique_id: str
    icon: str | None
    availability_topic: str
    payload_available: str
    payload_not_available: str
    state_topic: str
    value_template: str
    unit_of_measurement: str | None
    payload_on: str
    payload_off: str
    device: LinuxDeviceEntry
    device_class: str | None
    json_attributes_topic: str
    qos: int
