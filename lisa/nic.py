# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


import os
import re
from collections import OrderedDict
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from assertpy import assert_that

from lisa.tools import Echo, Ip
from lisa.util import InitializableMixin, LisaException, find_groups_in_lines

if TYPE_CHECKING:
    from lisa import Node


class NicInfo:

    # Class for info about an single upper/lower nic pair.
    # Devices using SRIOV on azure typically have an upper synthetic device
    # paired with a lower SRIOV Virtual Function (VF) device that
    # enables the passthrough to the physical NIC.

    # If sriov(AN) is not enabled then there will not be a lower SRIOV VF.
    # In this case, NicInfo will have lower = ""

    def __init__(
        self,
        upper: str,
        lower: str = "",
        pci_slot: str = "",
    ) -> None:
        self.upper = upper
        self.lower = lower
        self.pci_slot = pci_slot
        self.ip_addr = ""
        self.mac_addr = ""
        self.dev_uuid = ""
        self.bound_driver = ""
        self.driver_sysfs_path = PurePosixPath("")

    def __str__(self) -> str:
        return (
            "NicInfo:\n"
            f"upper: {self.upper}\n"
            f"lower: {self.lower}\n"
            f"pci_slot: {self.pci_slot}\n"
            f"ip_addr: {self.ip_addr}\n"
            f"mac_addr: {self.mac_addr}\n"
        )


class Nics(InitializableMixin):

    # Class for all of the nics on a node. Contains multiple NodeNic classes.
    # Init identifies upper/lower paired devices and the pci slot info for the lower.

    # regexes for seperating and parsing ip_addr_show entries
    # ex:
    """
    3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state ...
        UP group default qlen 1000
        link/ether 00:22:48:79:69:b4 brd ff:ff:ff:ff:ff:ff
        inet 10.0.1.4/24 brd 10.0.1.255 scope global eth1
        valid_lft forever preferred_lft forever
        inet6 fe80::222:48ff:fe79:69b4/64 scope link
        valid_lft forever preferred_lft forever
    4: enP13530s1: <BROADCAST,MULTICAST,SLAVE,UP,LOWER_UP> mtu 1500 ...
        qdisc mq master eth0 state UP group default qlen 1000
        link/ether 00:22:48:79:6c:c2 brd ff:ff:ff:ff:ff:ff
    6: ib0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 2044 qdisc mq state UP ...
        link/infiniband 00:00:09:27:fe:80:00:00:00:00:00:00:00:15:5d:...
        inet 172.16.1.118/16 brd 172.16.255.255 scope global ib0
            valid_lft forever preferred_lft forever
        inet6 fe80::215:5dff:fd33:ff7f/64 scope link
            valid_lft forever preferred_lft forever
    """
    __ip_addr_show_regex = re.compile(
        (
            r"\d+: (?P<name>\w+): \<.+\> .+\n\s+"
            r"link\/(?:ether|infiniband) (?P<mac>[0-9a-z:]+) .+\n?"
            r"(?:\s+inet (?P<ip_addr>[\d.]+)\/.*\n)?"
        )
    )

    # capturing from ip route show
    # ex:
    #    default via 10.57.0.1 dev eth0 proto dhcp src 10.57.0.4 metric 100
    __dev_regex = re.compile(
        r"default via\s+"  # looking for default route
        r"[0-9a-fA-F]{1,3}\."  # identify ip address
        r"[0-9a-fA-F]{1,3}\."
        r"[0-9a-fA-F]{1,3}\."
        r"[0-9a-fA-F]{1,3}"
        r"\s+dev\s+"  # looking for the device for the default route
        r"([a-zA-Z0-9]+)"  # capture device
    )

    # ex:
    # /sys/class/net/eth0/lower_enP13530s1 -> ../../../ (continued next line)
    # ad379351-34da-4568-93a3-03878ae8eee8/pci34da:00/34da:00:02.0/net/enP13530s1
    __nic_lower_regex = re.compile(
        (
            r"/sys/class/net/"
            r"([a-zA-Z0-9_\-]+)"  # upper interface GROUP1
            r"/lower_([a-zA-Z0-9_\-]+)"  # lower interface GROUP2
            r"/device -> ../../../"  # link to devices guid
            r"([a-zA-Z0-9]{4}:[a-zA-Z0-9]{2}:[a-zA-Z0-9]{2}.[a-zA-Z0-9])"  # bus info
        )
    )

    # /sys/class/net/enP35158p0s2/device -> ../../../8956:00:02.0
    __nic_vf_slot_regex = re.compile(
        (
            r"/sys/class/net/"
            r"([a-zA-Z0-9_\-]+)"  # lower interface name
            r"/device -> ../../../"  # link to devices guid
            r"([a-zA-Z0-9]{4}:[a-zA-Z0-9]{2}:[a-zA-Z0-9]{2}.[a-zA-Z0-9])"  # bus info
        )
    )

    _file_not_exist = re.compile(r"No such file or directory", re.MULTILINE)

    def __init__(self, node: "Node"):
        super().__init__()
        self._node = node
        self.nics: Dict[str, NicInfo] = OrderedDict()

    def __str__(self) -> str:
        _str = ""
        for nic in self.nics:
            _str += f"{self.nics[nic]}"
        return _str

    def __len__(self) -> int:
        return len(self.nics)

    def append(self, next_node: NicInfo) -> None:
        self.nics[next_node.upper] = next_node

    def is_empty(self) -> bool:
        return len(self.nics) == 0

    def get_unpaired_devices(self) -> List[str]:
        return [x.upper for x in self.nics.values() if not x.lower]

    def get_upper_nics(self) -> List[str]:
        return list(self.nics.keys())

    def get_lower_nics(self) -> List[str]:
        return [x.lower for x in self.nics.values() if x.lower]

    def get_device_slots(self) -> List[str]:
        return [x.pci_slot for x in self.nics.values() if x.pci_slot]

    # update the current nic driver in the NicInfo instance
    # grabs the driver short name and the driver sysfs path
    def get_nic_driver(self, nic_name: str) -> str:
        # get the current driver for the nic from the node
        # sysfs provides a link to the driver entry at device/driver
        nic = self.get_nic(nic_name)
        cmd = f"readlink -f /sys/class/net/{nic_name}/device/driver"
        # ex return value:
        # /sys/bus/vmbus/drivers/hv_netvsc
        found_link = self._node.execute(cmd, expected_exit_code=0).stdout
        assert_that(found_link).described_as(
            f"sysfs check for NIC device {nic_name} driver returned no output"
        ).is_not_equal_to("")
        nic.driver_sysfs_path = PurePosixPath(found_link)
        driver_name = nic.driver_sysfs_path.name
        assert_that(driver_name).described_as(
            f"sysfs entry contained no filename for device driver: {found_link}"
        ).is_not_equal_to("")
        nic.bound_driver = driver_name
        return driver_name

    def get_nic(self, nic_name: str) -> NicInfo:
        return self.nics[nic_name]

    def get_nic_by_index(self, index: int = -1) -> NicInfo:
        # get nic by index, default is -1 to give a non-primary nic
        # when there are more than one nic on the system
        number_of_nics = len(self.get_upper_nics())
        assert_that(number_of_nics).is_greater_than(0)
        try:
            nic_name = self.get_upper_nics()[index]
        except IndexError:
            raise LisaException(
                f"Attempted get_upper_nics()[{index}], only "
                f"{number_of_nics} nics are registered in node.nics. "
                f"Had upper interfaces: {self.get_upper_nics()}"
            )

        try:
            nic = self.nics[nic_name]
        except KeyError:
            raise LisaException(
                f"NicInfo for interface {nic_name} not found! "
                f"Had upper interfaces: {self.get_upper_nics()}"
            )
        return nic

    def nic_info_is_present(self, nic_name: str) -> bool:
        return nic_name in self.get_upper_nics() or nic_name in self.get_lower_nics()

    def unbind(self, nic: NicInfo) -> None:
        # unbind nic from current driver and return the old sysfs path
        echo = self._node.tools[Echo]
        # if sysfs path is not set, fetch the current driver
        if not nic.driver_sysfs_path:
            self.get_nic_driver(nic.upper)
        unbind_path = nic.driver_sysfs_path.joinpath("unbind")
        echo.write_to_file(
            nic.dev_uuid,
            unbind_path,
            sudo=True,
        )

    def bind(self, nic: NicInfo, driver_module_path: str) -> None:
        echo = self._node.tools[Echo]
        nic.driver_sysfs_path = PurePosixPath(driver_module_path)
        bind_path = nic.driver_sysfs_path.joinpath("bind")
        echo.write_to_file(
            nic.dev_uuid,
            self._node.get_pure_path(f"{str(bind_path)}"),
            sudo=True,
        )
        nic.bound_driver = nic.driver_sysfs_path.name

    def load_interface_info(self, nic_name: Optional[str] = None) -> None:
        command = "/sbin/ip addr show"
        if nic_name:
            command += f" {nic_name}"
        result = self._node.execute(
            command,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not run {command} on node {self._node.name}"
            ),
        )
        entries = find_groups_in_lines(
            result.stdout, self.__ip_addr_show_regex, single_line=False
        )
        found_nics = []
        for entry in entries:
            self._node.log.debug(f"Found nic info: {entry}")
            nic_name = entry["name"]
            mac = entry["mac"]
            ip_addr = entry["ip_addr"]
            if nic_name in self.get_upper_nics():
                nic_entry = self.nics[nic_name]
                nic_entry.ip_addr = ip_addr
                nic_entry.mac_addr = mac
                found_nics.append(nic_name)

        if not nic_name:
            assert_that(sorted(found_nics)).described_as(
                f"Could not locate nic info for all nics. "
                f"Nic set was {self.nics.keys()} and only found info for {found_nics}"
            ).is_equal_to(sorted(self.nics.keys()))

    def reload(self) -> None:
        self.nics.clear()
        self._initialize()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._node.log.debug("loading nic information...")
        self.nic_names = self._get_nic_names()
        self._get_node_nic_info()
        self._get_default_nic()
        self.load_interface_info()
        self._get_nic_uuids()
        for nic in self.get_upper_nics():
            self.get_nic_driver(nic)

    def _get_nic_names(self) -> List[str]:
        # identify all of the nics on the device, excluding tunnels and loopbacks etc.
        all_nics = self._node.execute(
            "ls /sys/class/net/",
            shell=True,
            sudo=True,
        ).stdout.split()
        virtual_nics = self._node.execute(
            "ls /sys/devices/virtual/net",
            shell=True,
            sudo=True,
        ).stdout.split()

        # remove virtual nics from the list
        non_virtual_nics = [x for x in all_nics if x not in virtual_nics]

        # verify if the nics names are not empty
        for item in non_virtual_nics:
            assert_that(item).described_as(
                "nic name could not be found"
            ).is_not_equal_to("")

        return non_virtual_nics

    def _get_nic_device(self, nic_name: str) -> str:
        slot_info_result = self._node.execute(
            f"readlink /sys/class/net/{nic_name}/device"
        )
        slot_info_result.assert_exit_code()
        base_device_result = self._node.execute(f"basename {slot_info_result.stdout}")
        base_device_result.assert_exit_code()
        # todo check addr matches expectation
        return base_device_result.stdout

    def _get_nic_uuid(self, nic_name: str) -> str:
        full_dev_path = self._node.execute(
            f"readlink /sys/class/net/{nic_name}/device",
            expected_exit_code_failure_message=(
                f"could not get sysfs device info for {nic_name}"
            ),
        )
        uuid = os.path.basename(full_dev_path.stdout.strip())
        self._node.log.debug(f"{nic_name} UUID:{uuid}")
        return uuid

    def _get_nic_uuids(self) -> None:
        for nic in self.get_upper_nics():
            self.nics[nic].dev_uuid = self._get_nic_uuid(nic)

    def _get_node_nic_info(self) -> None:
        # Identify which nics are slaved to master devices.
        # This should be really simple with /usr/bin/ip but experience shows
        # the tool isn't super consistent across distros in this regard

        # use sysfs to gather upper/lower nic pairings and pci slot info
        nic_info_fetch_cmd = "ls -la /sys/class/net/*/lower*/device"
        self._node.log.debug(f"Gathering NIC information on {self._node.name}.")
        result = self._node.execute(
            nic_info_fetch_cmd,
            shell=True,
        )
        if result.exit_code != 0:
            nic_info_fetch_cmd = "ls -la /sys/class/net/*/device"
            result = self._node.execute(
                nic_info_fetch_cmd,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="Could not grab NIC device info.",
            )

        for line in result.stdout.splitlines():
            sriov_match = self.__nic_lower_regex.search(line)
            if sriov_match:
                upper_nic, lower_nic, pci_slot = sriov_match.groups()
                nic_info = NicInfo(upper_nic, lower_nic, pci_slot)
                self.append(nic_info)
            sriov_match = self.__nic_vf_slot_regex.search(line)
            if sriov_match:
                lower_nic, pci_slot = sriov_match.groups()
                ip = self._node.tools[Ip]
                lower_nic_mac = ip.get_mac(lower_nic)
                for nic_name in [x for x in self.nic_names if x != lower_nic]:
                    upper_nic_mac = ip.get_mac(nic_name)
                    if upper_nic_mac == lower_nic_mac:
                        upper_nic = nic_name
                        nic_info = NicInfo(upper_nic, lower_nic, pci_slot)
                        self.append(nic_info)
                        break

        # Collects NIC info for any unpaired NICS
        for nic_name in [
            x
            for x in self.nic_names
            if x not in self.get_upper_nics() and x not in self.get_lower_nics()
        ]:
            nic_info = NicInfo(nic_name)
            self.append(nic_info)

        assert_that(len(self)).described_as(
            "During Lisa nic info initialization, Nics class could not "
            f"find any nics attached to {self._node.name}."
        ).is_greater_than(0)

    def _get_default_nic(self) -> None:
        cmd = "/sbin/ip route"
        ip_route_result = self._node.execute(cmd, shell=True, sudo=True)
        ip_route_result.assert_exit_code()
        assert_that(ip_route_result.stdout).is_not_empty()
        dev_match = self.__dev_regex.search(ip_route_result.stdout)
        if not dev_match or not dev_match.groups():
            raise LisaException(
                "Could not locate default network interface"
                f" in output:\n{ip_route_result.stdout}"
            )
        assert_that(dev_match.groups()).is_length(1)
        default_interface_name = dev_match.group(1)
        assert_that(default_interface_name in self.nic_names).described_as(
            (
                f"ERROR: NIC name found as default {default_interface_name} "
                f"was not in original list of nics {repr(self.nic_names)}."
            )
        ).is_true()
        self.default_nic: str = default_interface_name
        self.default_nic_route = str(dev_match)
