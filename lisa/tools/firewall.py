# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.base_tools import Service
from lisa.executable import Tool
from lisa.operating_system import Posix


class Firewall(Tool):
    @property
    def command(self) -> str:
        return "echo"

    @property
    def can_install(self) -> bool:
        return False

    def stop(self) -> None:
        cmd_result = self.node.execute("command -v ufw", shell=True)
        if 0 == cmd_result.exit_code:
            ufw = self.node.tools[Ufw]
            ufw.stop()
            return
        cmd_result = self.node.execute("command -v SuSEfirewall2", shell=True)
        if 0 == cmd_result.exit_code:
            susefirewall2 = self.node.tools[SuSEfirewall2]
            susefirewall2.stop()
            return
        cmd_result = self.node.execute("command -v firewall-cmd", shell=True)
        if 0 == cmd_result.exit_code:
            firewalld = self.node.tools[Firewalld]
            firewalld.stop()
            return
        cmd_result = self.node.execute("command -v iptables", shell=True)
        if 0 == cmd_result.exit_code:
            iptables = self.node.tools[Iptables]
            iptables.stop()
            return


class Ufw(Tool):
    @property
    def command(self) -> str:
        return "ufw"

    @property
    def can_install(self) -> bool:
        return False

    def stop(self) -> None:
        self.run("disable", shell=True, sudo=True, force_run=True)


class Iptables(Tool):
    @property
    def command(self) -> str:
        return "iptables"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        assert isinstance(self.node.os, Posix)
        self.node.os.install_packages("iptables")
        return self._check_exists()

    def accept(
        self,
        nic_name: str,
        dst_port: int,
        protocol: str = "tcp",
        policy: str = "ACCEPT",
    ) -> None:
        # accept all incoming traffic to `nic_name` with protocol `protocol`
        # and destination port `dst_port`
        self.run(
            (
                f"-A INPUT -i {nic_name} -p {protocol} "
                f"-m {protocol} --dport {dst_port} -j {policy}"
            ),
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"failed to set {policy} on {nic_name}:{dst_port}"
            ),
        )

    def start_forwarding(self, port: int, dst_ip: str, dst_port: int) -> None:
        self.run(
            f"-I FORWARD -o virbr0 -p tcp -d {dst_ip} --dport {dst_port} -j ACCEPT",
            sudo=True,
            expected_exit_code=0,
        )

        self.run(
            f"-t nat -I PREROUTING -p tcp --dport {port} -j DNAT --to {dst_ip}:{dst_port}",  # noqa: E501
            sudo=True,
            expected_exit_code=0,
        )

    def stop_forwarding(self, port: int, dst_ip: str, dst_port: int) -> None:
        self.run(
            f"-D FORWARD -o virbr0 -p tcp -d {dst_ip} --dport {dst_port} -j ACCEPT",
            sudo=True,
            expected_exit_code=0,
        )

        self.run(
            f"-t nat -D PREROUTING -p tcp --dport {port} -j DNAT --to {dst_ip}:{dst_port}",  # noqa: E501
            sudo=True,
            expected_exit_code=0,
        )

    def reset_table(self, name: str = "filter") -> None:
        self.run(
            f"-t {name} -F",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to reset table {name}",
        )

    def stop(self) -> None:
        self.run("-P INPUT ACCEPT", shell=True, sudo=True, force_run=True)
        self.run("-P OUTPUT ACCEPT", shell=True, sudo=True, force_run=True)
        self.run("-P FORWARD ACCEPT", shell=True, sudo=True, force_run=True)
        self.run("-P -F", shell=True, sudo=True, force_run=True)
    
    def add_iptable_rules(
        self,
        table_name: str = "filter",
        rules: list[str] = []
    ) -> None:
        for rule in rules:
            self.run(
                f"-t {table_name} {rule}",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=f"Failed to add iptable rule: {rule} in table {table_name}"
            )

    def remove_iptable_rules(
        self,
        rules: list[str] = []
    ) -> None:
        for rule in rules:
            self.run(
                f"-D {rule}",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=f"Failed to remove iptable rule: {rule}"
            )
    
    def create_iptable_chain(
        self,
        table_name: str,
        chain_names: list[str]
    ) -> None:
        
        for chain in chain_names:
            self.run(
                cmd = f"-t {table_name} -N {chain}",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=f"Failed to create chain {chain} in table {table_name}"
            )


class SuSEfirewall2(Tool):
    @property
    def command(self) -> str:
        return "SuSEfirewall2"

    @property
    def can_install(self) -> bool:
        return False

    def stop(self) -> None:
        service = self.node.tools[Service]
        service.stop_service("SuSEfirewall2")


class Firewalld(Tool):
    @property
    def command(self) -> str:
        return "firewall-cmd"

    @property
    def can_install(self) -> bool:
        return False

    def stop(self) -> None:
        service = self.node.tools[Service]
        service.stop_service("firewalld")
