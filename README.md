# linux2mqtt

> DISCLAIMER: See credits at the bottom to learn more about the original code for this project.

[![Mypy](https://github.com/miaucl/linux2mqtt/actions/workflows/mypy.yaml/badge.svg)](https://github.com/miaucl/linux2mqtt/actions/workflows/mypy.yaml)
[![Ruff](https://github.com/miaucl/linux2mqtt/actions/workflows/ruff.yml/badge.svg)](https://github.com/miaucl/linux2mqtt/actions/workflows/ruff.yml)
[![Markdownlint](https://github.com/miaucl/linux2mqtt/actions/workflows/markdownlint.yml/badge.svg)](https://github.com/miaucl/linux2mqtt/actions/workflows/markdownlint.yml)
[![Publish](https://github.com/miaucl/linux2mqtt/actions/workflows/publish.yml/badge.svg)](https://github.com/miaucl/linux2mqtt/actions/workflows/publish.yml)

Publish linux system performance metrics to a MQTT broker. It will also publish Home Assistant MQTT Discovery messages so that (binary) sensors automatically show up in Home Assistant.

_This is part of a family of similar tools:_

* [miaucl/linux2mqtt](https://github.com/miaucl/linux2mqtt)
* [miaucl/docker2mqtt](https://github.com/miaucl/docker2mqtt)
* [miaucl/systemctl2mqtt](https://github.com/miaucl/systemctl2mqtt)

It is available as python package on [pypi/linux2mqtt](https://pypi.org/p/linux2mqtt).
[![PyPI version](https://badge.fury.io/py/linux2mqtt.svg)](https://pypi.org/p/linux2mqtt)

`linux2mqtt` is a lightweight wrapper around [psutil](https://pypi.org/project/psutil/) that publishes CPU utilization, free memory, and other system-level stats to a MQTT broker. The primary use case is to collect system performance metrics for ingestion into [Home Assistant](https://www.home-assistant.io/) (HA) for alerting, reporting, and firing off any number of automations. However, given the minimal nature of this code, it could be used for other purposes as well.

## Installation and Deployment

It is available as python package on [pypi/linux2mqtt](https://pypi.org/p/linux2mqtt).

### Pypi package

[![PyPI version](https://badge.fury.io/py/linux2mqtt.svg)](https://pypi.org/p/linux2mqtt)

```bash
pip install linux2mqtt 
linux2mqtt --name MyServerName --cpu=60 --vm -vvvvv
```

Usage

```python
from linux2mqtt import Linux2Mqtt, DEFAULT_CONFIG

cfg = Linux2MqttConfig({ 
  **DEFAULT_CONFIG,
  "host": "mosquitto",
})

try:
  linux2mqtt = Linux2Mqtt(cfg)
  linux2mqtt.connect()
  linux2mqtt.loop_busy()

except Exception as ex:
  # Do something
```

This will install the latest release of `linux2mqtt`, create the necessary MQTT topics, and start sending virtual memory and CPU utilization metrics. The MQTT broker is assumed to be running on `localhost`. If your broker is running on a different host, specify the hostname or IP address using the `--host` parameter.

`linux2mqtt`requires Python 3.12 or above. If your default Python version is older, you may have to explicitly specify the `pip` version by using `pip3` or `pip-3`.

* The `--name` parameter is used for the friendly name of the sensor in Home Assistant and for the MQTT topic names. If not specified, it defaults to the hostname of the machine.
* Instantaneous CPU utilization isn't all that informative. It's normal for a CPU to occasionally spike to 100% for a few moments and means that the chip is being utilized to its full potential. However, if the CPU stays pegged at/near 100% over a longer period of time, it is indicative of a bottleneck. The `--cpu=60` parameter is the collection interval for the CPU metrics. Here CPU metrics are gathered for 60 seconds and then the average value is published to MQTT state topic for the sensor. A good value for this option is anywhere between 60 and 1800 seconds (1 to 15 minutes), depending on typical workloads.
* The `--vm` flag indicates that virtual memory (RAM) metrics should also be published.
* `-vvvvv` (five v's) specifies debug-level logging to the console. Reduce the quantity of v's to reduce the logging verbosity.

By default, `linux2mqtt` will publish system metrics every 30 seconds. This can be changed using the `--interval` option.

## Additional Metrics

### Disk Usage

`linux2mqtt` can publish disk usage metrics using the `du` option. Multiple `du` options can be specified to monitor different volumes. Each volume will present as a separate sensor in Home Assistant. The sensor state reports the percentage of total volume space consumed. Additional data (total volume size in bytes, free bytes, and used bytes) are accessible as state attributes on each sensor.

`linux2mqtt --name Server1 -vvvvv --cpu=60 --vm --du='/var/spool' --du='/'`

### Network Connections

Network connections are available with a single `--connections` flag, providing optional interval value (default `10` seconds). Adding this will poll your system for metrics like:

* How many total IP connections there are
* How many of those are IPv4
* How many of those are IPv6
* Which ports is the system currently listening on
* IP and port of any outbound connections (ones your system initiate to a remote device)
* IP and port of any inbound connections (ones another device is making of your system, along with the IP and port they're connecting to)

These metrics give you a better understanding of the network traffic interacting with your system.

### Network Throughput

Network throughput (amount of traffic) metrics are also available. Using one or more `--net` parameters, specify the interface name and the collection interval (as discussed in the CPU metrics documentation), separated by a comma. A separate MQTT topic is created for each interface and each will appear as a separate sensor in HA.

The sensor state equals average throughput of the interface during the collection interval (combining both transmit and receive) in kilobits per second. More detail is available in the state attributes, such as: individual TX and RX rates, number of packets, total bytes sent and received, etc. Except for TX and RX rates, all attribute values are total accumulated values since the interface was reset. Thus, expect to see very large numbers if the interface has been online a while.

`linux2mqtt --name Server1 -vvvvv --interval 60 --net=eth0,15`

This will publish network throughput information about Server1's `eth0` interface to the MQTT broker once every 60 seconds. The sensor state will equal the average network throughput over the previous 15 seconds.

### Thermal zones

`linux2mqtt` can publish temperature metrics for thermal zones using the `temp` option. Each thermal zone will present as a separate sensor in Home Assistant. The sensor state reports the temperature in `°C`. Additional data is accessible as state attributes on each sensor.

`linux2mqtt --name Server1 -vvvvv --cpu=60 --vm --temp`

### Fan speeds

`linux2mqtt` can publish fan speeds using the `fan` option. Each fan will present as a separate sensor in Home Assistant, but be aware this is only for monitoring which means it is not an actual fan entity but only presents itself as a sensor with **no** device class and **no** unit of measurements. The sensor state reports the fan speed in `RPM`. Additional data is accessible as state attributes on each sensor.

`linux2mqtt --name Server1 -vvvvv --cpu=60 --vm --fan`

### Package manager updates

`linux2mqtt` can iterate common package managers (currently `Apk` (Alpine), `Apt` (Debian, Ubuntu), `yum` (Centos, Rocky, Fedora)) to enquire about available updates to operating system packages, using the `--packages=` parameter. This provides the number of updates available and lists each updatable package.

By default, `linux2mqtt` will search for available updates every 3600 seconds. This can be changed specifying the desired interval in the parameter.

Enabling this option will cause increased network traffic in order to update package databases.

`linux2mqtt --name Server1 -vvvvv --packages=` will search for available updates every 1 hour

`linux2mqtt --name Server1 -vvvvv --packages=7200` will search for available updates every 2 hours

### Hard Drives

`linux2mqtt` can publish the status of all harddrives using the `harddrives` option. Each hard drive will present as a separate sensor in Home Assistant. The sensor state reports the harddrive status based on a the smartctl report, which generates a score. The details on the scoring methodology can be found below. Additional data is accessible as state attributes on each sensor.

`linux2mqtt --name Server1 -vvvvv --interval 60 --harddrives`

#### Scoring Methodology

The score to status conversion is:

| Status  | Score |
| ------- | ----- |
| HEALTHY | <= 10 |
| GOOD    | <= 20 |
| WARNING | <= 50 |
| FAILING | > 50  |

##### ATA Scoring

| SMART Attribute               | Penalty | Notes                          |
| ----------------------------- | ------- | ------------------------------ |
| Reallocated Sector Count      | ×2      | Indicates remapped bad sectors |
| Current Pending Sector        | ×3      | Sectors waiting reallocation   |
| Pending Sector > 10           | +30     | Additional penalty             |
| Offline Uncorrectable         | ×3      | Unrecoverable errors           |
| Reported Uncorrectable Errors | ×2      | Read/write failures            |
| Command Timeout               | ×1.5    | Communication delays           |
| UDMA CRC Error Count          | max +10 | Usually cable/interface issue  |

##### NVME Scoring

| SMART Attribute                 | Penalty | Notes                                      |
| ------------------------------- | ------- | ------------------------------------------ |
| critical_warning ≠ 0            | +100    | Any critical SMART flag triggers high risk |
| percent_used > 70%              | +10     | NAND wear indicator                        |
| percent_used > 80%              | +20     | Increased wear                             |
| percent_used > 90%              | +50     | Near end-of-life                           |
| media_errors                    | ×5      | Data integrity errors                      |
| num_error_log_entries           | max +50 | Error events (capped)                      |
| warning_temp_time > 0           | +10     | Drive exceeded warning temp                |
| critical_temp_time > 0          | +30     | Drive exceeded critical temp               |
| available_spare below threshold | +30     | Spare blocks depleted                      |

## Logging

`linux2mqtt` can log to a directory in addition to the console using the `--logdir` parameter. The specified directory can be absolute or relative and is created if it doesn't exist. The verbosity parameter applies to file logging and the log file size is limited to 1M bytes and 5 previous files are kept.

`linux2mqtt --name Server1 -vvvvv --logdir /var/log/linux2mqtt/`

## Compatibility

`linux2mqtt` has been tested to work on CentOS, Ubuntu, and Debian (Raspberry Pi), even tough some features are not available everywhere. **Python 3.12 (or above) is recommended.**

## Running in the Background (Daemonizing)

`linux2mqtt` runs as a foreground task at the command prompt. In order to run in the program in the background, or automatically at boot, the process has to be daemonized. The easiest way to do this is on a UNIX-like OS (Linux/BSD) is with [Supervisor](http://supervisord.org/) or [systemd](https://systemd.io). Example Supervisor and service configuration file for `linux2mqtt` is included in the [/contrib/](https://github.com/miaucl/linux2mqtt/blob/master/contrib/) directory.

## Discovery

It is possible to enable/disable discovery of the metrics.

`linux2mqtt --name Server1 -vvvvv --discovery "<your_discovery>"`

Setting it to an empty list will deactivate discovery, per default homeassistant is active.

`linux2mqtt --name Server1 -vvvvv --discovery ""`

## Using with Home Assistant (HA)

`linux2mqtt --name Server1 -vvvvv --discovery "homeassistant"`

Once `linux2mqtt` is collecting data and publishing it to MQTT, it's rather trivial to use the data in Home Assistant.

A few assumptions:

* **Home Assistant is already configured to use a MQTT broker.** Setting up MQTT and HA is beyond the scope of this documentation. However, there are a lot of great tutorials on YouTube. An external broker (or as add-on) like [Mosquitto](https://mosquitto.org/) will need to be installed and the HA MQTT integration configured.
* **The HA MQTT integration is configured to use `homeassistant` as the MQTT autodiscovery prefix.** This is the default for the integration and also the default for `linux2mqtt`. If you have changed this from the default, use the `--homeassistant-prefix` parameter to specify the correct one.
* **You're not using TLS to connect to the MQTT broker.** Currently `linux2mqtt` only works with unencrypted connections. Username / password authentication can be specified with the `--username` and `--password` parameters, but TLS encryption is not yet supported.

Using the default prefix and a system name of `NUC` (the name of the server), the following state can be found in the "States" section of Developer Tools in HA:

![Home Assistant Developer Tools screenshot](https://github.com/miaucl/linux2mqtt/blob/master/media/dev_tools_example.png?raw=true)

### Lovelace Dashboards

To visualize, use the excellent [mini-graph-card](https://github.com/kalkih/mini-graph-card) custom card for Lovelace dashboards. It's highly-customizable and fairly easy to make great looking charts in HA. Here is a very basic config example of using the metrics produced by `linux2mqtt` to display the past 12 hours of CPU and memory utilization on an Intel NUC server:

```yaml
entities:
  - entity: sensor.nuc_cpu
    name: CPU Utilization
    show_legend: true
    show_line: true
    show_points: false
  - entity: sensor.nuc_virtual_memory
    name: Memory Utilization
    show_legend: true
    show_line: true
    show_points: false
hours_to_show: 12
line_width: 2
lower_bound: 0
name: NUC System Metrics
points_per_hour: 6
show:
  labels: false
  labels_secondary: false
type: 'custom:mini-graph-card'
upper_bound: 100
```

![Example card in Home Assistant](https://github.com/miaucl/linux2mqtt/blob/master/docs/example_card.png?raw=true)

### Entities vs Attributes

Home assistant is moving away from `attributes` for additional data towards only entities. This is a slow process and currently attributes are the default way for this library, but it may be changed with following argument `--homeassistant-disable-attributes`

> HA doesn’t modify the number of sig figs for attributes because attributes are meant to be raw data. HA in general is moving away from them in favor of entities so that users can control things like sig fig.

## Documentation

Using `mkdocs`, the documentation and reference is generated and available on [github pages](https://miaucl.github.io/linux2mqtt/).

## Dev

Setup the dev environment using VSCode, it is highly recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_dev.txt
```

Install [pre-commit](https://pre-commit.com)

```bash
pre-commit install

# Run the commit hooks manually
pre-commit run --all-files
```

Following VSCode integrations may be helpful:

* [ruff](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff)
* [mypy](https://marketplace.visualstudio.com/items?itemName=matangover.mypy)
* [markdownlint](https://marketplace.visualstudio.com/items?itemName=DavidAnson.vscode-markdownlint)

To manually run the precommit checks without the pre-commit tool (this does
need the `requirements_dev.txt` to be installed as shown above):

```bash
ruff check
mypy linux2mqtt
```

### Releasing

A _final version_ can only be released from the `master` branch. To pass the gates of the `publish` workflow, the version must match in both the `tag` and `linux2mqtt/__init__.py`.

To release a prerelease version, it must be done from a feature branch (**not** `master`). Prerelease versions are explicitly marked as such on the GitHub release page.

## Credits

This is a detached fork from the repo <https://github.com/jamiebegin/linux2mqtt>, which does not seem to get evolved anymore.

> This project is intended to be an alternative to the (very good) [Glances](https://github.com/nicolargo/glances) project. The primary design difference is that the Glances integration into Home Assistant relies on periodically polling a RESTful API. However, the pub/sub model of [MQTT](http://mqtt.org/)--which is already widely used in the home automation community--is an ideal fit for real-time reporting of this type of data. Additionally `linux2mqtt` can be very lightweight because it omits the GUI and alerting elements of Glances (which are redundant when used in conjunction with HA).
