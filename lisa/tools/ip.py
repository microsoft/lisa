# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re

from assertpy import assert_that

from lisa.executable import Tool
from lisa.tools import Cat
from lisa.util import LisaException


class Ip(Tool):
    # 00:0d:3a:c5:13:6f
    __mac_address_pattern = re.compile(
        "[0-9a-f]{2}([-:]?)[0-9a-f]{2}(\\1[0-9a-f]{2}){4}$", re.M
    )

    @property
    def command(self) -> str:
        return "ip"

    def _check_exists(self) -> bool:
        return True

    def _set_device_status(self, nic_name: str, status: str) -> None:
        self.node.execute(
            f"ip link set {nic_name} {status}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not set {nic_name} to '{status}'"
            ),
        )

    def up(self, nic_name: str) -> None:
        self._set_device_status(nic_name, "up")

    def down(self, nic_name: str) -> None:
        self._set_device_status(nic_name, "down")

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

    def restart_device(self, nic_name: str) -> None:
        self.node.execute(
            f"ip link set dev {nic_name} down;ip link set dev {nic_name} up",
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
            raise LisaException(f"MAC address {mac_address} is invaild")
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
