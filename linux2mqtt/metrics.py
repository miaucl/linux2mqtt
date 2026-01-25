"""linux2mqtt metrics."""

import logging
from queue import Queue
import socket
import threading
import time
from typing import Any, Self

import jsons
import psutil

from .const import (
    MAX_CPU_INTERVAL,
    MAX_NET_INTERVAL,
    MIN_CPU_INTERVAL,
    MIN_NET_INTERVAL,
)
from .exceptions import (
    HardDriveException,
    Linux2MqttConfigException,
    Linux2MqttException,
    Linux2MqttMetricsException,
    NoPackageManagerFound,
)
from .helpers import addr_ip, addr_port, is_addr, sanitize
from .package_manager import PackageManager, get_package_manager
from .type_definitions import LinuxDeviceEntry, LinuxEntry, MetricEntities, SensorType
from .harddrive import HardDrive, get_hard_drive

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
    unit_of_measurement: str | None = None
    device_class: str | None = None
    icon: str | None = None
    state_field: str = "state"
    homeassistant_entities: list[MetricEntities] = []

    ha_sensor_type: SensorType = "sensor"

    polled_result: dict[str, str | int | float | list[str] | list[int] | None] | None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize base class."""
        self.polled_result = None

    def get_discovery(
        self,
        state_topic: str,
        linux2mqtt_availability_topic: str,
        availability_topic: str,
        device_definition: LinuxDeviceEntry,
        disable_attributes: bool,
    ) -> list[LinuxEntry]:
        """Get the discovery topic config data.

        Parameters
        ----------
        state_topic
            The state topic where to find the data for state and attributes
        linux2mqtt_availability_topic
            The availability topic for linux2mqtt
        availability_topic
            The availability topic for the entry
        device_definition
            The device entry for the homeassistant config
        disable_attributes
            Should only one entity be created with attributes or all data as entities

        Returns
        -------
        LinuxEntry
            The homeassistant config entry

        """
        return (
            [
                LinuxEntry(
                    {
                        "name": self.name,
                        "unique_id": f"{device_definition['identifiers']}_{self.name_sanitized}",
                        "availability": [
                            {"topic": linux2mqtt_availability_topic},
                            {"topic": availability_topic.format(self.name_sanitized)},
                        ],
                        "availability_mode": "all",
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
                        "json_attributes_topic": state_topic.format(
                            self.name_sanitized
                        ),
                        "qos": 1,
                    }
                )
            ]
            if not disable_attributes
            else [
                LinuxEntry(
                    {
                        "name": entity["name"],
                        "unique_id": f"{device_definition['identifiers']}_{sanitize(entity['name'])}",
                        "availability": [
                            {"topic": linux2mqtt_availability_topic},
                            {"topic": availability_topic.format(self.name_sanitized)},
                        ],
                        "availability_mode": "all",
                        "payload_available": "online",
                        "payload_not_available": "offline",
                        "state_topic": state_topic.format(self.name_sanitized),
                        "value_template": f"{{{{ value_json.{entity['state_field']} if value_json is not undefined and value_json.{entity['state_field']} is not undefined else None }}}}",
                        "unit_of_measurement": entity["unit_of_measurement"],
                        "icon": entity["icon"],
                        "device_class": entity["device_class"],
                        "payload_on": "on",
                        "payload_off": "off",
                        "device": device_definition,
                        "json_attributes_topic": None,
                        "qos": 1,
                    }
                )
                for entity in self.homeassistant_entities
            ]
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

    _name = "CPU"
    icon = "mdi:chip"
    unit_of_measurement = "%"
    state_field = "used"
    homeassistant_entities = [
        MetricEntities(
            {
                "name": f"CPU {f}",
                "state_field": f,
                "icon": "mdi:chip",
                "unit_of_measurement": "%",
                "device_class": None,
            }
        )
        for f in [
            "user",
            "nice",
            "system",
            "idle",
            "iowait",
            "irq",
            "softirq",
            "steal",
            "guest",
            "guest_nice",
            "used",
        ]
    ]

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
    homeassistant_entities = [
        MetricEntities(
            {
                "name": "Virtual Memory",
                "state_field": "percent",
                "icon": "mdi:memory",
                "unit_of_measurement": "%",
                "device_class": None,
            }
        ),
        *[
            MetricEntities(
                {
                    "name": f"Virtual Memory {f}",
                    "state_field": f,
                    "icon": "mdi:memory",
                    "unit_of_measurement": "MB",
                    "device_class": "data_size",
                }
            )
            for f in [
                "total",
                "available",
                "used",
                "free",
                "active",
                "inactive",
            ]
        ],
    ]

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
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish virtual memory data"
            ) from ex
        else:
            return False


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
        self.homeassistant_entities = [
            MetricEntities(
                {
                    "name": self._name_template.format(mountpoint),
                    "state_field": "percent",
                    "icon": "mdi:harddisk",
                    "unit_of_measurement": "%",
                    "device_class": None,
                }
            ),
            *[
                MetricEntities(
                    {
                        "name": f"{self._name_template.format(mountpoint)} {f}",
                        "state_field": f,
                        "icon": "mdi:harddisk",
                        "unit_of_measurement": "GB",
                        "device_class": "data_size",
                    }
                )
                for f in [
                    "total",
                    "used",
                    "free",
                ]
            ],
        ]

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
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish disk usage data"
            ) from ex
        else:
            return False


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
        """Initialize the network thread.

        Parameters
        ----------
        result_queue: Queue[BaseMetric]
            The queue to put the metric into once the data is gathered
        metric
            The network metric to gather data for
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
        """Run the network thread. Once data is gathered, it is put into the queue and the thread exits.

        Raises
        ------
        Linux2MqttMetricsException
            network information could not be gathered or prepared for publishing

        """
        try:
            start_tx = 0
            start_rx = 0
            # get initial counters
            nics = psutil.net_io_counters(pernic=True)
            if self.nic in nics:
                start_tx = nics[self.nic].bytes_sent
                start_rx = nics[self.nic].bytes_recv
            else:
                metric_logger.warning("Network %s not available", self.nic)
                return
            time.sleep(self.interval)
            # get counters after interval
            nics = psutil.net_io_counters(pernic=True)
            if self.nic in nics:
                end_tx = nics[self.nic].bytes_sent
                end_rx = nics[self.nic].bytes_recv
            else:
                metric_logger.warning("Network %s not available", self.nic)
                return
            # handle counter rollover by ignoring bytes from start_tx/start_rx to maxvalue
            if end_tx >= start_tx:
                diff_tx = end_tx - start_tx
            else:
                diff_tx = end_tx
            if end_rx >= start_rx:
                diff_rx = end_rx - start_rx
            else:
                diff_rx = end_rx
            # calculate rate bytes/sec and convert bytes to kilobits/sec
            tx_rate = diff_tx / self.interval / 125.0
            rx_rate = diff_rx / self.interval / 125.0

            self.metric.polled_result = {
                "total_rate": int(tx_rate + rx_rate),
                "tx_rate": int(tx_rate),
                "rx_rate": int(rx_rate),
            }
            self.result_queue.put(self.metric)
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
        self.homeassistant_entities = [
            MetricEntities(
                {
                    "name": f"{self._name_template.format(nic)} {f}",
                    "state_field": f,
                    "icon": "mdi:server-network",
                    "unit_of_measurement": "kbit/s",
                    "device_class": "data_rate",
                }
            )
            for f in [
                "total_rate",
                "tx_rate",
                "rx_rate",
            ]
        ]

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


class NetConnectionMetrics(BaseMetric):
    """Network connections metric."""

    _name = "Network Connections"
    icon = "mdi:ip-network"
    device_class = ""
    unit_of_measurement = ""
    state_field = "count"
    homeassistant_entities = [
        MetricEntities(
            {
                "name": f"Network connections {f}",
                "state_field": f,
                "icon": "mdi:ip-network",
                "unit_of_measurement": None,
                "device_class": None,
            }
        )
        for f in [
            "total",
            "ipv4",
            "ipv6",
        ]
    ]

    def __init__(self, interval: int) -> None:
        """Extract local IPs for evaluation during poll.

        Parameters
        ----------
        interval
            The interval to gather data over

        """
        super().__init__()
        interface_addrs = psutil.net_if_addrs()
        self.ips = set()
        self.interval = interval

        for snicaddrs in interface_addrs.values():
            for snicaddr in snicaddrs:
                if snicaddr.family in (socket.AF_INET, socket.AF_INET6):
                    self.ips.add(snicaddr.address)

    def poll(self, result_queue: Queue[Self]) -> bool:
        """Poll new data for the network connection metrics.

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
            network connection information could not be gathered or prepared for publishing

        """
        try:
            st = psutil.net_connections()

            listening_ports = {
                addr_port(x.laddr)
                for x in st
                if x.status == "LISTEN"
                and is_addr(x.laddr)
                and addr_ip(x.laddr) in ("0.0.0.0", "::")
            }

            established = [x for x in st if x.status == "ESTABLISHED"]

            self.polled_result = {
                "count": len(established),  # deprecated
                "total": len(established),
                "ipv4": len(
                    [
                        x
                        for x in established
                        if x.family == socket.AF_INET
                        and is_addr(x.laddr)
                        and not addr_ip(x.laddr).startswith("127.")
                    ]
                ),
                "ipv6": len(
                    [
                        x
                        for x in established
                        if x.family == socket.AF_INET6
                        and is_addr(x.laddr)
                        and addr_ip(x.laddr) != "::1"
                    ]
                ),
                "listening_ports": list(listening_ports),
                "outbound": [
                    f"{addr_ip(x.raddr)}:{addr_port(x.raddr)}"
                    for x in established
                    if is_addr(x.laddr)
                    and is_addr(x.raddr)
                    and addr_ip(x.laddr) in self.ips
                    and addr_ip(x.raddr) not in ("127.0.0.1", "::1")
                ],
                "inbound": [
                    f"{addr_ip(x.raddr)}:{addr_port(x.raddr)} -> "
                    f"{addr_ip(x.laddr)}:{addr_port(x.laddr)}"
                    for x in established
                    if is_addr(x.laddr)
                    and is_addr(x.raddr)
                    and addr_port(x.laddr) in listening_ports
                ],
            }

        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish net connections"
            ) from ex
        else:
            return False


class TempMetrics(BaseMetric):
    """Thermal zones metric."""

    icon = "mdi:thermometer"
    device_class = "temperature"
    unit_of_measurement = "°C"
    state_field = "current"

    _name_template = "Thermal Zone ({}/{})"
    _device: str
    _idx: int
    _label: str

    def __init__(self, device: str, idx: int, label: str):
        """Initialize the thermal zone metric.

        Parameters
        ----------
        device
            The device
        idx
            The 0-based index of the thermal zone within the list of zones for this device
        label
            The label of the zone (can be empty)

        Raises
        ------
        Linux2MqttConfigException
            Bad config

        """
        super().__init__()
        self._device = device
        self._idx = idx
        if not label:
            # 1-based to match lm-sensors
            label = f"temp{idx + 1}"
        self._label = label
        self._name = self._name_template.format(device, label)
        self.homeassistant_entities = [
            MetricEntities(
                {
                    "name": f"{self._name_template.format(device, label)} {f}",
                    "state_field": f,
                    "icon": "mdi:thermometer",
                    "unit_of_measurement": "°C",
                    "device_class": "temperature",
                }
            )
            for f in [
                "current",
            ]
        ]

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
            Thermal zone information could not be gathered or prepared for publishing

        """
        try:
            st = psutil.sensors_temperatures()
            dev = st.get(self._device)
            assert dev
            thermal_zone = dev[self._idx]
            assert thermal_zone
            self.polled_result = {
                "label": self._label,
                "current": thermal_zone.current,
                "high": thermal_zone.high,
                "critical": thermal_zone.critical,
            }
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish thermal zone data"
            ) from ex
        else:
            return False


class FanSpeedMetrics(BaseMetric):
    """Fan speed metric."""

    icon = "mdi:fan"
    device_class = ""
    unit_of_measurement = ""
    state_field = "current"

    _name_template = "Fan Speed ({}/{})"
    _device: str
    _idx: int
    _label: str

    def __init__(self, device: str, idx: int, label: str):
        """Initialize the fan speed metric.

        Parameters
        ----------
        device
            The device
        idx
            The 0-based index of the fan within the list of fans for this device
        label
            The label of the fan (can be empty)

        Raises
        ------
        Linux2MqttConfigException
            Bad config

        """
        super().__init__()
        self._device = device
        self._idx = idx
        if not label:
            # 1-based to match lm-sensors
            label = f"fan{idx + 1}"
        self._label = label
        self._name = self._name_template.format(device, label)
        self.homeassistant_entities = [
            MetricEntities(
                {
                    "name": f"{self._name_template.format(device, label)} {f}",
                    "state_field": f,
                    "icon": "mdi:fan",
                    "unit_of_measurement": None,
                    "device_class": None,
                }
            )
            for f in [
                "current",
            ]
        ]

    def poll(self, result_queue: Queue[Self]) -> bool:
        """Poll new data for the fan speed metric.

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
            Fan speed information could not be gathered or prepared for publishing

        """
        try:
            st = psutil.sensors_fans()
            dev = st.get(self._device)
            assert dev
            fan = dev[self._idx]
            assert fan
            self.polled_result = {
                "label": self._label,
                "current": fan.current,
                "unit": "rpm",
            }
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish fan speed data"
            ) from ex
        else:
            return False


class PackageUpdateMetricThread(BaseMetricThread):
    """Package Update metric thread."""

    def __init__(
        self,
        result_queue: Queue[BaseMetric],
        metric: BaseMetric,
        package_manager: PackageManager,
    ):
        """Initialize the package update thread.

        Parameters
        ----------
        result_queue
            The queue to put the metric into once the data is gathered
        metric
            The package update metric to gather data for
        package_manager
            The system specific interface for a package manager

        """
        threading.Thread.__init__(self)
        self.result_queue = result_queue
        self.metric = metric
        self.package_manager = package_manager

    def run(self) -> None:
        """Run the package update thread.

        Once data is gathered, it is put into the queue and the thread exits.

        Raises
        ------
        Linux2MqttMetricsException
            package update information could not be gathered or prepared for publishing

        """
        try:
            self.package_manager.update_if_needed()
            updates_available = self.package_manager.get_available_updates()
            self.metric.polled_result = {
                "count": len(updates_available),  # deprecated
                "total": len(updates_available),
                "packages": updates_available,
            }
            self.result_queue.put(self.metric)
        except Exception as ex:
            raise Linux2MqttMetricsException(
                "Could not gather and publish package update data"
            ) from ex


class PackageUpdateMetrics(BaseMetric):
    """Package update metrics.

    Attributes
    ----------
    package_manager
        The system specific interface for a package manager

    """

    icon = "mdi:package-up"
    device_class = ""
    unit_of_measurement = ""
    state_field = "count"
    homeassistant_entities = [
        MetricEntities(
            {
                "name": "Package updates",
                "state_field": "total",
                "icon": "mdi:package-up",
                "unit_of_measurement": None,
                "device_class": None,
            }
        )
    ]

    _name = "Package Updates"
    package_manager: PackageManager

    def __init__(self, update_interval: int, is_privileged: bool):
        """Initialize the package update metric.

        Parameters
        ----------
        update_interval
            The interval between invokes of update (if applicable)

        is_privileged
            If the invoking user has effective user ID 0 (root)

        Raises
        ------
        ValueError
            Bad interval defined

        Linux2MqttException
            An acceptable package manager has not been found

        """
        super().__init__()

        try:
            self.package_manager = get_package_manager(update_interval, is_privileged)
        except NoPackageManagerFound as ex:
            raise Linux2MqttException(
                "Failed to find a suitable package manager. Currently supported are: apt, apk, yum"
            ) from ex

    def poll(self, result_queue: Queue[BaseMetric]) -> bool:
        """Poll new data for the package updates metric.

        Parameters
        ----------
        result_queue
            The queue where to post new data once gathered

        Returns
        -------
        bool
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
                "Cannot start package update metric due to missing result_queue"
            ) from ex
        self.result_queue = result_queue
        th = PackageUpdateMetricThread(
            result_queue=result_queue,
            metric=self,
            package_manager=self.package_manager,
        )
        th.daemon = True
        th.start()
        return True  # Expect a deferred result

class HardDriveMetricThread(BaseMetricThread):
    """Hard Drive metric thread."""

    def __init__(
        self, result_queue: Queue[BaseMetric], metric: BaseMetric, harddrive: HardDrive
    ):
        """Initialize the HardDrive thread.

        Parameters
        ----------
        result_queue
            The queue to put the metric into once the data is gathered
        metric
            The hard drive metric to gather data for
        harddrive
            The type of hard drive to gather data over

        """
        threading.Thread.__init__(self)
        self.result_queue = result_queue
        self.metric = metric
        self.harddrive = harddrive

    def run(self) -> None:
        """Run the hard drive thread. Once data is gathered, it is put into the queue and the thread exits.

        Raises
        ------
        Linux2MqttMetricsException
            hard drive information could not be gathered or prepared for publishing

        """
        try:
            # 
            self.harddrive.parse_attributes()
            self.metric.polled_result = {
                **self.harddrive.attributes,  # type: ignore[unused-ignore]
            }
            # self.metric._name = self.harddrive.attributes['model_name']
            self.result_queue.put(self.metric)
        except Exception as ex:
            raise Linux2MqttMetricsException(
                f"Could not gather and publish hard drive data {self.metric._name}"
            ) from ex
        
class HardDriveMetrics(BaseMetric):
    """Hard Drive metric."""

    icon = "mdi:harddisk"
    device_class = "" # TODO See if I can have categories for this
    unit_of_measurement = ""
    state_field = "status"

    _name_template = "Hard Drive (ID:{})"
    _device: str
    _thermal_zone: str

    def __init__(self, device: str):
        """Initialize the hard drive metric.

        Parameters
        ----------
        device
            The device

        Raises
        ------
        Linux2MqttException
            Bad config

        """
        super().__init__()

        try:
            self.harddrive = get_hard_drive(device_name=device)
            self._name = self._name_template.format(device)
        except HardDriveException as ex:
            raise Linux2MqttException(
                "Failed to find a suitable hard drive type. Currently supported are: Hard Disk and NVME"
            ) from ex
        
        

    def poll(self, result_queue: Queue[Self]) -> bool:
        """Poll new data for the hard drive metric.

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
                "Cannot start hard drive metric due to missing result_queue"
            ) from e
        self.result_queue = result_queue
        th = HardDriveMetricThread(
            result_queue=result_queue, 
            metric=self,
            harddrive=self.harddrive

        )
        th.daemon = True
        th.start()
        return True  # Expect a deferred result