# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re

from assertpy import assert_that

from lisa.executable import Tool
from lisa.tools import Cat
from lisa.tools.start_configuration import StartConfiguration
from lisa.tools.whoami import Whoami
from lisa.util import LisaException


class Ip(Tool):
    # 00:0d:3a:c5:13:6f
    __mac_address_pattern = re.compile(
        "[0-9a-f]{2}([-:]?)[0-9a-f]{2}(\\1[0-9a-f]{2}){4}$", re.M
    )
    __ip_addr_show_regex = re.compile(
        (
            r"\d+: (?P<name>\w+): \<.+\> .+\n\s+"
            r"link\/(?:ether|infiniband) (?P<mac>[0-9a-z:]+) .+\n?"
            r"(?:\s+inet (?P<ip_addr>[\d.]+)\/.*\n)?"
        )
    )

    @property
    def command(self) -> str:
        return "ip"

    def _check_exists(self) -> bool:
        return True

    def _set_device_status(
        self, nic_name: str, status: str, persist: bool = False
    ) -> None:
        self.node.execute(
            f"ip link set {nic_name} {status}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not set {nic_name} to '{status}'"
            ),
        )
        if persist:
            self.node.tools[StartConfiguration].add_command(
                f"ip link set {nic_name} {status}"
            )

    def up(self, nic_name: str, persist: bool = False) -> None:
        self._set_device_status(nic_name, "up", persist=persist)

    def down(self, nic_name: str, persist: bool = False) -> None:
        self._set_device_status(nic_name, "down", persist=persist)

    def addr_flush(self, nic_name: str) -> None:
        self.node.execute(
            f"ip addr flush dev {nic_name}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not flush address for device {nic_name}"
            ),
        )

    def add_ipv4_address(self, nic_name: str, ip: str, persist: bool = True) -> None:
        self.run(
            f"addr add {ip} dev {nic_name}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not add address to device {nic_name}"
            ),
        )
        if persist:
            self.node.tools[StartConfiguration].add_command(
                f"ip addr add {ip} dev {nic_name}"
            )

    def restart_device(self, nic_name: str) -> None:
        self.node.execute(
            (
                f"ip link set dev {nic_name} down;ip link set dev {nic_name} up;"
                "dhclient -r;dhclient"
            ),
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"fail to restart [down then up] the nic {nic_name}"
            ),
        )

    def get_mtu(self, nic_name: str) -> int:
        cat = self.node.tools[Cat]
        return int(cat.read(f"/sys/class/net/{nic_name}/mtu", force_run=True))

    def set_mtu(self, nic_name: str, mtu: int) -> None:
        self.run(f"link set dev {nic_name} mtu {mtu}", force_run=True, sudo=True)
        new_mtu = self.get_mtu(nic_name=nic_name)
        assert_that(new_mtu).described_as("set mtu failed").is_equal_to(mtu)

    def set_mac_address(self, nic_name: str, mac_address: str) -> None:
        if not self.__mac_address_pattern.match(mac_address):
            raise LisaException(f"MAC address {mac_address} is invalid")
        self.down(nic_name)
        try:
            self.node.execute(
                f"/sbin/ip link set {nic_name} address {mac_address}",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"fail to set mac address {mac_address} for nic {nic_name}"
                ),
            )
        finally:
            self.up(nic_name)

    def nic_exists(self, nic_name: str) -> bool:
        result = self.run(f"link show {nic_name}", force_run=True, sudo=True)
        return not (
            (result.stderr and "not exist" in result.stderr)
            or (result.stdout and "not exist" in result.stdout)
        )

    def get_mac(self, nic_name: str) -> str:
        result = self.run(f"link show {nic_name}", force_run=True, sudo=True)
        matched = self.__ip_addr_show_regex.match(result.stdout)
        assert matched
        return matched.group("mac")

    def setup_bridge(self, name: str, ip: str) -> None:
        if self.nic_exists(name):
            self._log.debug(f"Bridge {name} already exists")
            return

        # create bridge
        self.run(
            f"link add {name} type bridge",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Could not create bridge {name}",
        )
        self.add_ipv4_address(name, ip)
        self.up(name)

    def set_bridge_configuration(self, name: str, key: str, value: str) -> None:
        self.run(
            f"link set dev {name} type bridge {key} {value}",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not set bridge {name} configuation: {key} {value}"
            ),
        )
        self.restart_device(name)

    def delete_interface(self, name: str) -> None:
        # check if the interface exists
        if not self.nic_exists(name):
            self._log.debug(f"Interface {name} does not exist")
            return

        # delete interface
        self.down(name)
        self.run(
            f"link delete {name}",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Could not delete interface {name}",
        )

    def set_master(self, child_interface: str, master_interface: str) -> None:
        self.run(
            f"link set dev {child_interface} master {master_interface}",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not set bridge {master_interface} as master for"
                f" {child_interface}"
            ),
        )

    def setup_tap(self, name: str, bridge: str) -> None:
        if self.nic_exists(name):
            self._log.debug(f"Tap {name} already exists")
            return

        # create tap
        user = self.node.tools[Whoami].run().stdout.strip()
        self.run(
            f"tuntap add {name} mode tap user {user} multi_queue",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Could not create tap {name}",
        )

        # add tap to bridge
        self.set_master(name, bridge)

        # start interface
        self.up(name)
