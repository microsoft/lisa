# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import ipaddress
import itertools
import os
import re
from typing import Any, Dict, List, Tuple

from assertpy import assert_that, fail

from lisa import Node
from lisa.tools import Echo
from lisa.util import InitializableMixin, LisaException


class NicInfo:

    # Class for info about an single upper/lower nic pair.
    # devices using SRIOV on azure typically have an upper synthetic device
    # paired with a lower SRIOV Virtual Function (VF) device that
    # enables the passthrough to the physical NIC.

    def __init__(
        self,
        upper: str,
        lower: str = "",
        pci_slot: str = "",
    ) -> None:
        self.has_lower = lower != "" or pci_slot == ""
        self.upper = upper
        self.lower = lower
        self.pci_slot = pci_slot
        self.ip_addr = ""
        self.mac_addr = ""
        self.dev_uuid = ""
        self.bound_driver = "hv_netvsc"  # NOTE: azure default

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

    # for parsing ip addr show (ipv4)
    # ex:
    """
    eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group
        default qlen 1000
    link/ether 60:45:bd:86:d4:88 brd ff:ff:ff:ff:ff:ff
    inet 10.57.0.4/24 brd 10.57.0.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::6245:bdff:fe86:d488/64 scope link
       valid_lft forever preferred_lft forever
    """
    __ip_regex = re.compile(
        r"inet\s+"  # looking for ip address in output
        r"([0-9a-fA-F]{1,3}\."  # capture ipv4 address
        r"[0-9a-fA-F]{1,3}\."
        r"[0-9a-fA-F]{1,3}\."
        r"[0-9a-fA-F]{1,3})"
    )
    __mac_regex = re.compile(
        r"ether\s+"  # looking for the ether address
        r"([0-9a-fA-F]{2}:"  # capture mac address
        r"[0-9a-fA-F]{2}:"
        r"[0-9a-fA-F]{2}:"
        r"[0-9a-fA-F]{2}:"
        r"[0-9a-fA-F]{2}:"
        r"[0-9a-fA-F]{2})"
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

    def __init__(self, node: Node):
        super().__init__()
        self._node = node
        self._nics: Dict[str, NicInfo] = dict()

    def __str__(self) -> str:
        _str = ""
        for nic in self._nics:
            _str += f"{self._nics[nic]}"
        return _str

    def __len__(self) -> int:
        return len(self._nics)

    def append(self, next_node: NicInfo) -> None:
        self._nics[next_node.upper] = next_node

    def is_empty(self) -> bool:
        return len(self._nics) == 0

    def get_unpaired_devices(self) -> List[str]:
        return [x.upper for x in self._nics.values() if not x.has_lower]

    def get_upper_nics(self) -> List[str]:
        return [self._nics[x].upper for x in self._nics.keys()]

    def get_lower_nics(self) -> List[str]:
        return [self._nics[x].lower for x in self._nics.keys()]

    def get_device_slots(self) -> List[str]:
        return [self._nics[x].pci_slot for x in self._nics.keys()]

    def get_nic(self, nic_name: str) -> NicInfo:
        return self._nics[nic_name]

    def get_test_nic(self) -> Tuple[int, NicInfo]:
        # convenience method
        # get the 'last' nic in the list of nics
        number_of_nics = len(self.get_upper_nics())
        assert_that(number_of_nics).is_greater_than(0)
        # will be used for tests with a single active vf, so id = 0
        return (0, self._nics[self.get_upper_nics()[number_of_nics - 1]])

    def nic_info_is_present(self, nic_name: str) -> bool:
        return nic_name in self.get_upper_nics() or nic_name in self.get_lower_nics()

    def unbind(self, nic: NicInfo, driver_module: str) -> None:
        echo = self._node.tools[Echo]
        echo.write_to_file(
            nic.dev_uuid,
            self._node.get_pure_path(f"/sys/bus/vmbus/drivers/{driver_module}/unbind"),
            sudo=True,
        )

    def bind(self, nic: NicInfo, driver_module: str) -> None:
        echo = self._node.tools[Echo]
        echo.write_to_file(
            nic.dev_uuid,
            self._node.get_pure_path(f"/sys/bus/vmbus/drivers/{driver_module}/bind"),
            sudo=True,
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._nic_names = self._get_nic_names()
        self._get_node_nic_info()
        self.default_nic = self._get_default_nic()
        self._get_host_if_info()
        self._get_nic_uuids()

    def _get_nic_names(self) -> List[str]:
        # identify all of the nics on the device, excluding tunnels and loopbacks etc.
        result = self._node.execute(
            " ls /sys/class/net/ | grep -Ev $(ls /sys/devices/virtual/net)",
            shell=True,
            sudo=True,
        )
        nic_names = result.stdout.splitlines()
        for item in nic_names:
            assert_that(item).described_as(
                "nic name could not be found"
            ).is_not_equal_to("")
        return nic_names

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
            self._nics[nic].dev_uuid = self._get_nic_uuid(nic)

    def _get_node_nic_info(self) -> None:
        # Identify which nics are slaved to master devices.
        # This should be really simple with /usr/bin/ip but experience shows
        # the tool isn't super consistent across distros in this regard

        # use sysfs to gather upper/lower nic pairings and pci slot info
        for pairing in itertools.permutations(self._nic_names, 2):
            upper_nic, lower_nic = pairing
            # check a nic pairing to identify upper/lower relationship
            upper_check = self._node.execute(
                f"readlink /sys/class/net/{lower_nic}/upper_{upper_nic}"
            )
            if upper_check.exit_code == 0:
                assert_that(upper_check.stdout).is_not_equal_to("")
                pci_slot = self._get_nic_device(lower_nic)
                assert_that(pci_slot).is_not_empty()
                # check pcislot info looks correct
                nic_info = NicInfo(upper_nic, lower_nic, pci_slot)
                self.append(nic_info)

        # identify nics which don't have a pairing (non-AN devices)
        for nic in self._nic_names:
            if not self.nic_info_is_present(nic):
                self.append(NicInfo(nic))

        assert_that(self).described_as(
            (
                "During Lisa nic info initialization, Nics class could not "
                f"find any nics attached to {self._node.name}."
            )
        ).is_not_empty()

    def _get_default_nic(self) -> str:
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
        assert_that(default_interface_name in self._nic_names).described_as(
            (
                f"ERROR: NIC name found as default {default_interface_name} "
                f"was not in original list of nics {repr(self._nic_names)}."
            )
        ).is_true()
        return default_interface_name

    def _get_host_if_info(self) -> None:
        for nic in self.get_upper_nics():
            # get ip and mac
            result = self._node.execute(f"/sbin/ip addr show {nic}", shell=True)
            result.assert_exit_code()
            ip_match = self.__ip_regex.search(result.stdout)
            mac_match = self.__mac_regex.search(result.stdout)

            if ip_match and mac_match:
                # check we found matches for both
                for match in [ip_match, mac_match]:
                    assert_that(match.groups()).described_as(
                        (
                            f"(IP) Trouble parsing `ip addr show {nic}` output."
                            " Number of match groups was unexpected."
                        )
                    ).is_length(1)

                ip_addr = ip_match.group(1)
                mac_addr = mac_match.group(1)

                # double check IP address looks right
                ipaddress.ip_address(ip_addr)

                # save them both off
                self.get_nic(nic).ip_addr = ip_addr
                self.get_nic(nic).mac_addr = mac_addr
            else:
                fail(f"Could not parse output of ip addr show {nic}")
