# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import shlex
from typing import List, Optional

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools.firewall import Firewall
from lisa.tools.kill import Kill


class Dnsmasq(Tool):
    @property
    def command(self) -> str:
        return "dnsmasq"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages("dnsmasq")
        return self._check_exists()

    def start(
        self,
        nic_name: str,
        gateway: str,
        dhcp_range: str,
        stop_firewall: bool = True,
        kill_existing: bool = True,
        pid_file: str = "",
        lease_file: str = "",
        dhcp_options: Optional[List[str]] = None,
    ) -> None:
        if stop_firewall:
            # stop firewall
            self.node.tools[Firewall].stop()

        if kill_existing:
            # kill dnsmasq if it is running
            kill = self.node.tools[Kill]
            kill.by_name("dnsmasq")

        if not pid_file:
            pid_file = f"/var/run/qemu-dnsmasq-{nic_name}.pid"
        if not lease_file:
            lease_file = f"/var/run/qemu-dnsmasq-{nic_name}.leases"

        # setup dnsmasq on interface `nic_name` and listen on `nic_address`
        # assign dhcp address in `dhcp_range`
        command_parts = [
            "--strict-order",
            "--except-interface=lo",
            f"--interface={nic_name}",
            f"--listen-address={gateway}",
            "--bind-interfaces",
            f"--dhcp-range={dhcp_range}",
            "--conf-file=",
            f"--pid-file={pid_file}",
            f"--dhcp-leasefile={lease_file}",
            "--dhcp-no-override",
        ]
        if dhcp_options:
            command_parts.extend(
                f"--dhcp-option={dhcp_option}" for dhcp_option in dhcp_options
            )
        cmd = shlex.join(command_parts)

        # start dnsmasq
        self.run(
            cmd,
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to start dnsmasq",
        )
