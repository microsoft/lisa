# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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
    ) -> None:
        # stop firewall
        self.node.tools[Firewall].stop()

        # kill dnsmasq if it is running
        kill = self.node.tools[Kill]
        kill.by_name("dnsmasq")

        # setup dnsmasq on interface `nic_name` and listen on `nic_address`
        # assign dhcp address in `dhcp_range`
        cmd = (
            "--strict-order --except-interface=lo "
            f"--interface={nic_name} --listen-address={gateway} --bind-interfaces "
            f"--dhcp-range={dhcp_range} --conf-file= "
            f"--pid-file=/var/run/qemu-dnsmasq-{nic_name}.pid "
            f"--dhcp-leasefile=/var/run/qemu-dnsmasq-{nic_name}.leases "
            "--dhcp-no-override "
        )

        # start dnsmasq
        self.run(
            cmd,
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to start dnsmasq",
        )
