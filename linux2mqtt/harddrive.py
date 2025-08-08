"""Hard drives"""

from subprocess import DEVNULL, PIPE, STDOUT, Popen, run
from time import time
import re

from .exceptions import HardDriveException


class HardDrive:
    """Base class for all harddrives to implement"""
    #parameters
    
    def __init__(self, device_id: str):
        """Initialize the hard drive metric.

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
        self._device = device_id
        # self._name = self._name = self._name_template.format(device_) Use the device name from smartctl for the device name

        pass

    def _get_attributes():
        pass

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
    

