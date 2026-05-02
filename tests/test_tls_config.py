"""Tests for MQTT TLS configuration behavior."""

from argparse import Namespace
from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock

from linux2mqtt.const import DEFAULT_CONFIG, MQTT_PORT_DEFAULT, MQTT_TLS_PORT_DEFAULT
from linux2mqtt.exceptions import Linux2MqttConfigException
from linux2mqtt.linux2mqtt import Linux2Mqtt, _derive_mqtt_port, _validate_tls_args

TLS_CONFIG_KEYS = (
    "mqtt_tls_enabled",
    "mqtt_tls_ca_cert",
    "mqtt_tls_client_cert",
    "mqtt_tls_client_key",
    "mqtt_tls_insecure",
)


def _args(**overrides: object) -> Namespace:
    """Create an argparse namespace with default TLS arguments."""
    defaults = {
        "port": None,
        "tls": False,
        "tls_ca": None,
        "tls_cert": None,
        "tls_key": None,
        "tls_insecure": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


class TlsConfigTests(TestCase):
    """Tests for TLS defaults and validation."""

    def test_legacy_config_without_tls_keys_does_not_configure_tls(self) -> None:
        """Treat configs without TLS keys as TLS-disabled configs."""
        cfg = deepcopy(DEFAULT_CONFIG)
        for key in TLS_CONFIG_KEYS:
            del cfg[key]
        linux2mqtt = Linux2Mqtt(cfg)
        linux2mqtt.mqtt = Mock()
        linux2mqtt._cleanup = Mock()

        linux2mqtt._configure_tls()

        linux2mqtt.mqtt.tls_set_context.assert_not_called()

    def test_mqtt_port_defaults_to_plain_mqtt_without_tls(self) -> None:
        """Use the standard MQTT port when TLS is disabled."""
        self.assertEqual(_derive_mqtt_port(_args()), MQTT_PORT_DEFAULT)

    def test_mqtt_port_defaults_to_tls_port_with_tls(self) -> None:
        """Use the standard TLS MQTT port when TLS is enabled."""
        self.assertEqual(
            _derive_mqtt_port(_args(tls=True)),
            MQTT_TLS_PORT_DEFAULT,
        )

    def test_explicit_mqtt_port_overrides_tls_default(self) -> None:
        """Preserve explicit port overrides even when TLS is enabled."""
        self.assertEqual(_derive_mqtt_port(_args(port=1884, tls=True)), 1884)

    def test_tls_specific_args_require_tls_flag(self) -> None:
        """Reject TLS-specific arguments when TLS itself is disabled."""
        with self.assertRaises(Linux2MqttConfigException):
            _validate_tls_args(_args(tls_ca="ca.pem"))

    def test_tls_cert_and_key_must_be_provided_together(self) -> None:
        """Reject client certificate authentication without a full cert/key pair."""
        with self.assertRaises(Linux2MqttConfigException):
            _validate_tls_args(_args(tls=True, tls_cert="client.pem"))
