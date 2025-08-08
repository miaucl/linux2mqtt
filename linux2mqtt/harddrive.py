"""Hard drives"""

from enum import Enum
import json
import shlex
from subprocess import DEVNULL, PIPE, STDOUT, Popen, run
import subprocess
from time import time
import re

from .exceptions import HardDriveException, Linux2MqttException

class HARDDRIVESTATUS(Enum):
    HEALTHY = 'healthy'
    GOOD = 'good'
    WARNING = 'warning'
    FAILING = 'failing'


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
        with Popen(
            command,
            stdout=PIPE,
            stderr=DEVNULL,
            text=True,
        ) as proc:
            stdout, stderr = proc.communicate(timeout=30)

            if proc.returncode != 0:
                raise HardDriveException(
                    f"Something went wrong with smartctl: {proc.returncode}: '{stderr}'"
                )
            
            raw_json_data = json.loads(stdout)
            
        # output  = subprocess.run(command, capture_output=True)

        # raw_json_data = json.loads(output.stdout)
        self._attributes = raw_json_data

    def parse_attributes(self):
        """Hard Drive specific parse function depending on results from smartctl."""
        raise Linux2MqttException from NotImplementedError
    

    def get_status_score(self):
        """Hard Drive specific score function depending on results from smartctl."""
        raise Linux2MqttException from NotImplementedError



class SataDrive(HardDrive):

    def parse_attributes(self):
        ata_smart_attributes = [("Reallocated Sector Count", 5), ("Command Timeout", 38), ("Reported Uncorrectable Errors",187),
                                ("Current Pending Sector", 197), ("Offline Uncorrectable", 198), ("UDMA CRC Error Count", 199),
                                ]

        self.attributes["Model Name"] = self._attributes['model_name']
        self.attributes["Device"] = self._attributes['device']['name']
        self.attributes["Size TB"] = self._attributes['user_capacity']['bytes']/1000000000000
        self.attributes["Temperature"] = self._attributes['temperature']['current']
        self.attributes["Smart status"] = 'Healthy' if self._attributes['smart_status']['passed'] else 'Failed'
        self.attributes["Power On Time"] = self._attributes['power_on_time']['hours']
        self.attributes["Power Cycle Count"] = self._attributes['power_cycle_count']
    
        new_data = {item['id']: item for item in self._attributes['ata_smart_attributes']['table']}
        for name, key in ata_smart_attributes:
            tmp = new_data[key]['raw']['value'] if new_data.get(key) else None
            if tmp:
                self.attributes[name] = tmp

        self.attributes['status'] = self.get_status_score()


    def get_status_score(self):
        score = 0
        score += self.attributes.get('Reallocated Sector Count',0) * 2
        if self.attributes.get('Reallocated Sector Count',0) > 50:
            score += 50

        score += self.attributes.get('Current Pending Sector',0) * 3
        if self.attributes.get('Current Pending Sector',0) > 10:
            score += 30

        score += self.attributes.get('Offline Uncorrectable',0) * 3
        score += self.attributes.get('Reported Uncorrectable Errors',0) * 2
        score += self.attributes.get('Command Timeout',0) * 1.5
        score += min(self.attributes.get('UDMA CRC Error Count',0), 10)

        # SMART CTL isnt consistent enough to come up with a percentage used for SSDs....
        # if 'percent_used' in attributes:
        #     if attributes['percent_used'] > 90:
        #         score += 30
        #     elif attributes['percent_used'] > 80:
        #         score += 10

        if score <= 10:
            return HARDDRIVESTATUS.HEALTHY
        elif score <= 20:
            return HARDDRIVESTATUS.GOOD
        elif score <= 50:
            return HARDDRIVESTATUS.WARNING
        else:
            return HARDDRIVESTATUS.FAILING


class NVME(HardDrive):
    def parse_attributes(self):
        nvme_smart_attributes = ['critical_warning', 'percentage_used', 'power_on_hours', 'power_cycles', 'media_errors', 'num_err_log_entries',
                                 'critical_comp_time', 'warning_temp_time', 'available_spare', 'available_spare_threshold']
               
        self.attributes["Model Name"] = self._attributes['model_name']
        self.attributes["Device"] = self._attributes['device']['name']
        self.attributes["Size TB"] = self._attributes['user_capacity']['bytes']/1000000000000
        self.attributes["Temperature"] = self._attributes['temperature']['current']
        self.attributes["Smart status"] = 'Healthy' if self._attributes['smart_status']['passed'] else 'Failed'

        for key in nvme_smart_attributes:
            tmp = self._attributes['nvme_smart_health_information_log'].get(key)
            if tmp:
                self.attributes[key] = tmp
        
        self.attributes['status'] = self.get_status_score()



    def get_status_score(self):
        score = 0

        # Critical warnings (bitmask)
        if self.attributes.get('critical_warning') != 0:
            score += 100  # Any critical flag = high risk

        # NAND wear
        if self.attributes.get('percent_used') > 90:
            score += 50
        elif self.attributes.get('percent_used') > 80:
            score += 20
        elif self.attributes.get('percent_used') > 70:
            score += 10

        # Media/data errors
        score += self.attributes.get('media_errors') * 5

        # Error log entries
        score += min(self.attributes.get('num_error_log_entries'), 50)  # cap at 50

        # Temperature issues
        if self.attributes.get('critical_temp_time') > 0:
            score += 30
        elif self.attributes.get('warning_temp_time') > 0:
            score += 10

        # Available spare
        if self.attributes.get('available_spare') < self.attributes.get('available_spare_threshold'):
            score += 30

        # Classification
        if score <= 10:
            return HARDDRIVESTATUS.HEALTHY
        elif score <= 20:
            return HARDDRIVESTATUS.GOOD
        elif score <= 50:
            return HARDDRIVESTATUS.WARNING
        else:
            return HARDDRIVESTATUS.FAILING
    


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
        return SataDrive(device_name)
    elif r2.match(device_name):
        return NVME(device_name)
    else:
        return None
        raise HardDriveException
    

