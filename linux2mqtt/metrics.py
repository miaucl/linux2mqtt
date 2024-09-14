"""linux2mqtt metrics."""

import logging
from queue import Queue
import threading
import time
from typing import Any, Dict

import jsons  # type: ignore
import numpy as np
import psutil
from typing_extensions import Self

from .const import (
    MAX_CPU_INTERVAL,
    MAX_NET_INTERVAL,
    MIN_CPU_INTERVAL,
    MIN_NET_INTERVAL,
)
from .exceptions import (
    Linux2MqttConfigException,
    Linux2MqttException,
    Linux2MqttMetricsException,
)
from .helpers import sanitize
from .type_definitions import LinuxDeviceEntry, LinuxEntry, SensorType

metric_logger = logging.getLogger("metrics")


class BaseMetric:
    """Base metric class.

    Attributes
    ----------
    _name
        the name of the metric
    unit_of_measurement
        The unit of the metric
    device_class
        The device_class of the metric
    icon
        The icon of the metric
    state_field
        The field for the state in the data dict of .polled_result
    ha_sensor_typ
        The sensor type of the metric
    polled_result
        The dict with the polled result data for the state and attributes

    """

    _name: str
    unit_of_measurement: str = ""
    device_class: str = ""
    icon: str = ""
    state_field: str = "state"

    ha_sensor_type: SensorType = "sensor"

    polled_result: Dict[str, str | int | float | None] | None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize base class."""
        self.polled_result = None

    def get_discovery(
        self,
        state_topic: str,
        availability_topic: str,
        device_definition: LinuxDeviceEntry,
    ) -> LinuxEntry:
        """Get the discovery topic config data.

        Parameters
        ----------
        state_topic
            The state topic where to find the data for state and attributes
        availability_topic
            The availability topic for the entry
        device_definition
            The device entry fro the homeassistant config

        Returns
        -------
        LinuxEntry
            The homeassistant config entry

        """
        return LinuxEntry(
            {
                "name": self.name,
                "unique_id": f"{device_definition['identifiers']}_{self.name_sanitized}",
                "availability_topic": availability_topic.format(self.name_sanitized),
                "payload_available": "online",
                "payload_not_available": "offline",
                "state_topic": state_topic.format(self.name_sanitized),
                "value_template": f"{{{{ value_json.{self.state_field} if value_json is not undefined and value_json.{self.state_field} is not undefined else None }}}}",
                "unit_of_measurement": self.unit_of_measurement,
                "icon": self.icon,
                "device_class": self.device_class,
                "payload_on": "on",
                "payload_off": "off",
                "device": device_definition,
                "json_attributes_topic": state_topic.format(self.name_sanitized),
                "qos": 1,
            }
        )

    def poll(self, result_queue: Queue[Any]) -> bool:
        """Poll new data for the metric. Can happened instantly or lazily (separate thread for example).

        Parameters
        ----------
        result_queue
            The queue where to post new data if data is gathered lazily

        Returns
        -------
        bool
            False if data is readily available, True if data is gathered lazily

        Raises
        ------
        Linux2MqttException
            General exception.

        """
        raise Linux2MqttException from NotImplementedError

    @property
    def name(self) -> str:
        """Return the name of the metric.

        Returns
        -------
        str
            The metrics name

        """
        return self._name

    @property
    def name_sanitized(self) -> str:
        """Return the sanitized name of the metric.

        Returns
        -------
        str
            The metrics sanitized name

        """
        return sanitize(self._name)


class BaseMetricThread(threading.Thread):
    """Base metric thread.

    Attributes
    ----------
    result_queue
        The queue to put the metric into once data is gathered
    metric
        The metric to gather data for
    interval
        The interval to gather data over

    """

    result_queue: Queue[BaseMetric]
    metric: BaseMetric
    interval: int


class CPUMetricThread(BaseMetricThread):
    """CPU metric thread."""

    def __init__(
        self, result_queue: Queue[BaseMetric], metric: BaseMetric, interval: int
    ):
        """Initialize the cpu thread.

        Parameters
        ----------
        result_queue
            The queue to put the metric into once the data is gathered
        metric
            The cpu metric to gather data for
        interval
            The interval to gather data over

        """
        threading.Thread.__init__(self)
        self.result_queue = result_queue
        self.metric = metric
        self.interval = interval

    def run(self) -> None:
        """Run the cpu thread. Once data is gathered, it is put into the queue and the thread exits.

        Raises
        ------
        Linux2MqttMetricsException
            cpu information could not be gathered or prepared for publishing

        """
        try:
            cpu_times = psutil.cpu_times_percent(interval=self.interval, percpu=False)
            self.metric.polled_result = {
                **jsons.dump(cpu_times),  # type: ignore[unused-ignore]
                "used": 100.0 - cpu_times.idle,
            }
            self.result_queue.put(self.metric)
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish cpu data"
            ) from ex


class CPUMetrics(BaseMetric):
    """CPU metric.

    Attributes
    ----------
    interval
        The interval to gather cpu data over

    """

    _name = "cpu"
    icon = "mdi:chip"
    unit_of_measurement = "%"
    state_field = "used"

    interval: int

    def __init__(self, interval: int):
        """Initialize the cpu metric.

        Raises
        ------
        Linux2MqttConfigException
            Bad config

        """
        super().__init__()
        self.interval = interval

        if interval < MIN_CPU_INTERVAL:
            raise Linux2MqttConfigException(
                "cpu metric could not start due to bad config"
            ) from ValueError(
                f"The interval for the cpu must at least {MIN_CPU_INTERVAL}s"
            )
        elif interval > MAX_CPU_INTERVAL:
            raise Linux2MqttConfigException(
                "cpu metric could not start due to bad config"
            ) from ValueError(
                f"The interval for the cpu must at most {MAX_CPU_INTERVAL}s"
            )

    def poll(self, result_queue: Queue[BaseMetric]) -> bool:
        """Poll new data for the cpu metric.

        Parameters
        ----------
        result_queue
            The queue where to post new data once gathered

        Returns
        -------
        bool = False
            True as the data is gathered lazily

        Raises
        ------
        Linux2MqttException
            General exception


        """
        try:
            assert result_queue
        except ReferenceError as ex:
            raise Linux2MqttException(
                "Cannot start cpu metric due to missing result_queue"
            ) from ex
        self.result_queue = result_queue
        th = CPUMetricThread(
            result_queue=result_queue, metric=self, interval=self.interval
        )
        th.daemon = True
        th.start()
        return True  # Expect a deferred result


class VirtualMemoryMetrics(BaseMetric):
    """Virtual memory metric."""

    _name = "Virtual Memory"
    icon = "mdi:memory"
    device_class = "data_size"
    unit_of_measurement = "MB"
    state_field = "used"

    def poll(self, result_queue: Queue[Self]) -> bool:
        """Poll new data for the virtual memory metric.

        Parameters
        ----------
        result_queue
            (Unused)

        Returns
        -------
        bool
            True as the data is readily available

        Raises
        ------
        Linux2MqttMetricsException
            virtual memory information could not be gathered or prepared for publishing

        """
        try:
            vm = psutil.virtual_memory()
            self.polled_result = {
                "total": float(vm.total) / 1_000_000,
                "available": float(vm.available) / 1_000_000,
                "percent": vm.percent,
                "used": float(vm.used) / 1_000_000,
                "free": float(vm.free) / 1_000_000,
                "active": float(vm.active) / 1_000_000,
                "inactive": float(vm.inactive) / 1_000_000,
            }
            return False
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish virtual memory data"
            ) from ex


class DiskUsageMetrics(BaseMetric):
    """Disk usage metrics.

    Attributes
    ----------
    _name_template
        The template to create the name using the mountpoint as value
    mountpoint
        The mountpoint to check the metric

    """

    icon = "mdi:harddisk"
    device_class = "data_size"
    unit_of_measurement = "GB"
    state_field = "used"

    _name_template = "Disk Usage (Volume:{})"
    mountpoint: str

    def __init__(self, mountpoint: str):
        """Initialize the disk usage metric."""
        super().__init__()
        self.mountpoint = mountpoint
        self._name = self._name_template.format(mountpoint)

    def poll(self, result_queue: Queue[Self]) -> bool:
        """Poll new data for the virtual memory metric.

        Parameters
        ----------
        result_queue
            (Unused)

        Returns
        -------
        bool
            True as the data is readily available

        Raises
        ------
        Linux2MqttMetricsException
            virtual memory information could not be gathered or prepared for publishing

        """
        try:
            disk = psutil.disk_usage(self.mountpoint)
            self.polled_result = {
                "total": float(disk.total) / 1_000_000_000,
                "used": float(disk.used) / 1_000_000_000,
                "free": float(disk.free) / 1_000_000_000,
                "percent": disk.percent,
            }

            return False
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish disk usage data"
            ) from ex


class NetworkMetricThread(BaseMetricThread):
    """Network metric thread.

    Attributes
    ----------
    nic
        The network interface to gather data for.

    """

    def __init__(
        self,
        result_queue: Queue[BaseMetric],
        metric: BaseMetric,
        interval: int,
        nic: str,
    ):
        """Initialize the cpu thread.

        Parameters
        ----------
        result_queue: Queue[BaseMetric]
            The queue to put the metric into once the data is gathered
        metric
            The cpu metric to gather data for
        interval
            The interval to gather data over
        nic
            The network interface

        """
        threading.Thread.__init__(self)
        self.result_queue = result_queue
        self.metric = metric
        self.interval = interval
        self.nic = nic

    def run(self) -> None:
        """Run the cpu thread. Once data is gathered, it is put into the queue and the thread exits.

        Raises
        ------
        Linux2MqttMetricsException
            network information could not be gathered or prepared for publishing

        """
        try:
            x = 0
            interval = self.interval
            tx_bytes = []
            rx_bytes = []
            prev_tx = 0
            prev_rx = 0
            base_tx = 0
            base_rx = 0
            while x < interval:
                nics = psutil.net_io_counters(pernic=True)
                if self.nic in nics:
                    tx = nics[self.nic].bytes_sent
                    rx = nics[self.nic].bytes_recv
                    if tx < prev_tx:
                        # TX counter rollover
                        base_tx += prev_tx
                    if rx < prev_rx:
                        # RX counter rollover
                        base_rx += prev_rx
                    tx_bytes.append(base_tx + tx)
                    rx_bytes.append(base_rx + rx)
                    prev_tx = tx
                    prev_rx = rx
                time.sleep(1)
                x += 1

            if self.nic in nics:
                tx_rate_bytes_sec = np.average(np.diff(np.array(tx_bytes)))
                tx_rate = tx_rate_bytes_sec / 125.0  # bytes/sec to kilobits/sec
                rx_rate_bytes_sec = np.average(np.diff(np.array(rx_bytes)))
                rx_rate = rx_rate_bytes_sec / 125.0  # bytes/sec to kilobits/sec

                self.metric.polled_result = {
                    "total_rate": int(tx_rate + rx_rate),
                    "tx_rate": int(tx_rate),
                    "rx_rate": int(rx_rate),
                }
                self.result_queue.put(self.metric)
            else:
                metric_logger.warning("Network %s not available", self.nic)
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish network data"
            ) from ex


class NetworkMetrics(BaseMetric):
    """Network metric thread.

    Attributes
    ----------
    _name_template
        The template to create the name using the nic as value
    interval
        The interval to gather cpu data over
    nic
        The network interface to gather data for.

    """

    icon = "mdi:server-network"
    device_class = "data_rate"
    unit_of_measurement = "kbit/s"
    state_field = "total_rate"

    _name_template = "Network Throughput (NIC:{})"
    interval: int
    nic: str

    def __init__(self, nic: str, interval: int):
        """Initialize the network metric.

        Parameters
        ----------
        nic
            The network interface
        interval
            The interval to gather data over

        Raises
        ------
        Linux2MqttConfigException
            Bad config

        """
        super().__init__()
        self.interval = interval
        self.nic = nic
        self._name = self._name_template.format(nic)

        if interval < MIN_NET_INTERVAL:
            raise ValueError(
                f"The interval for the network {nic} must at least {MIN_NET_INTERVAL}s"
            )
        elif interval > MAX_NET_INTERVAL:
            raise ValueError(
                f"The interval for the network {nic} must at most {MAX_NET_INTERVAL}s"
            )

    def poll(self, result_queue: Queue[BaseMetric]) -> bool:
        """Poll new data for the network metric.

        Parameters
        ----------
        result_queue
            The queue where to post new data once gathered

        Returns
        -------
        bool = False
            True as the data is gathered lazily

        Raises
        ------
        Linux2MqttException
            General exception

        """
        try:
            assert result_queue
        except ReferenceError as e:
            raise Linux2MqttException(
                "Cannot start network metric due to missing result_queue"
            ) from e
        self.result_queue = result_queue
        th = NetworkMetricThread(
            result_queue=result_queue, metric=self, interval=self.interval, nic=self.nic
        )
        th.daemon = True
        th.start()
        return True  # Expect a deferred result


class TempMetrics(BaseMetric):
    """Thermal zones metric."""

    icon = "mdi:thermometer"
    device_class = "temperature"
    unit_of_measurement = "°C"
    state_field = "current"

    _name_template = "Thermal Zone ({}/{})"
    _device: str
    _thermal_zone: str

    def __init__(self, device: str, thermal_zone: str):
        """Initialize the thermal zone metric.

        Parameters
        ----------
        device
            The device
        thermal_zone
            The thermal zone

        Raises
        ------
        Linux2MqttConfigException
            Bad config

        """
        super().__init__()
        self._device = device
        self._thermal_zone = thermal_zone
        self._name = self._name_template.format(device, thermal_zone)

    def poll(self, result_queue: Queue[Self]) -> bool:
        """Poll new data for the thermal zone metric.

        Parameters
        ----------
        result_queue
            (Unused)

        Returns
        -------
        bool
            True as the data is readily available

        Raises
        ------
        Linux2MqttMetricsException
            thermal zone information could not be gathered or prepared for publishing

        """
        try:
            st = psutil.sensors_temperatures()  # type: ignore
            thermal_zone = next(
                (
                    item
                    for item in st.get(self._device, [])
                    if item.label == self._thermal_zone
                ),
                None,
            )
            assert thermal_zone
            self.polled_result = {
                "label": thermal_zone.label,
                "current": thermal_zone.current,
                "high": thermal_zone.high,
                "critical": thermal_zone.critical,
            }
            return False
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish thermal zone data"
            ) from ex
