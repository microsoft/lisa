# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from assertpy import assert_that

from lisa.executable import Tool
from lisa.tools import Cat


class Ip(Tool):
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
            f"ip link set dev {nic_name} down;ip link set dev {nic_name} up", shell=True
        )

    def get_mtu(self, nic_name: str) -> int:
        cat = self.node.tools[Cat]
        return int(cat.read(f"/sys/class/net/{nic_name}/mtu", force_run=True))

    def set_mtu(self, nic_name: str, mtu: int) -> None:
        self.run(f"link set dev {nic_name} mtu {mtu}", force_run=True, sudo=True)
        new_mtu = self.get_mtu(nic_name=nic_name)
        assert_that(new_mtu).described_as("set mtu failed").is_equal_to(mtu)
