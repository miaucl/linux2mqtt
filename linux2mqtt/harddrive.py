"""Hard drives"""

import json
import shlex
from subprocess import DEVNULL, PIPE, STDOUT, Popen, run
import subprocess
from time import time
import re

from .exceptions import HardDriveException, Linux2MqttException


class HardDrive:
    """Base class for all harddrives to implement"""
    #parameters
    _attributes = None
    device_id: str

    def __init__(self, device_id: str):
        """Initialize the hard drive metric.

        Parameters
        ----------
        device_id
            The device id from /dev/disk/by-id/
        
        """
        self.device_id = device_id
        # self._name = self._name = self._name_template.format(device_) Use the device name from smartctl for the device name

        pass

    def _get_attributes(self):
        command = shlex.split(f"/usr/sbin/smartctl --info --all --json --nocheck standby /dev/disk/by-id/{self.device_id}")
        output  = subprocess.run(command, capture_output=True)

        raw_json_data = json.loads(output.stdout)
        self._attributes = raw_json_data

    def parse_attributes(self):
        """Hard Drive specific parse function depending on results from smartctl."""
        raise Linux2MqttException from NotImplementedError

class HardDisk(HardDrive):
    pass

class NVME(HardDrive):
    pass


# Create a class for Spinning disks and one for NVME
# In the argparse, have the code create a metric for each of the harddrives found in potential disks
# The metric can be HDD / SSD depending on the regex match
# Create a thread for the actual execution of the command as it relies on running subprocess command



    

def get_hard_drive(device_name:str) -> HardDrive:
    """Determine the hard drive type.

    Returns
    -------
    HardDrive
        The specific hard drive type for drive id

    """

    ata_regex = "^ata.*(?<!part\d)$"
    nvme_regex = "^nvme-eui.*(?<!part\d)$"
    # potential_disks = os.listdir("/dev/disk/by-id/")

    r1 = re.compile(ata_regex)
    r2 = re.compile(nvme_regex)

    if r1.match(device_name):
        return HardDisk(device_name)
    elif r2.match(device_name):
        return NVME(device_name)
    else:
        return None
        raise HardDriveException
    

