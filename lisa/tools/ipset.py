# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Ipset(Tool):
    @property
    def command(self) -> str:
        return "ipset"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages([self])
        return self._check_exists()

    def create_ipset(
        self,
        set_name: str,
        set_type: str = "ip",
    ) -> None:
        cmd = f"create {set_name} hash:{set_type}"

        self.run(
            cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to create ipset",
        )

    def add_ip(
        self,
        set_name: str,
        ip_address: str,
    ) -> None:
        cmd = f"add {set_name} {ip_address}"

        self.run(
            cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to add ip to ipset",
        )
