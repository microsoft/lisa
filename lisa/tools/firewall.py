# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool

from .service import Service


class Firewall(Tool):
    @property
    def command(self) -> str:
        return "ls -lt"

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
        self.run("disable", shell=True, sudo=True)


class Iptables(Tool):
    @property
    def command(self) -> str:
        return "iptables"

    @property
    def can_install(self) -> bool:
        return False

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

    def stop(self) -> None:
        self.run("-P INPUT ACCEPT", shell=True, sudo=True)
        self.run("-P OUTPUT ACCEPT", shell=True, sudo=True)
        self.run("-P FORWARD ACCEPT", shell=True, sudo=True)
        self.run("-P -F", shell=True, sudo=True)


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
