# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.operating_system import Posix


class Conntrack(Tool):
    @property
    def command(self) -> str:
        return "conntrack"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages([self])
        return self._check_exists()

    def create_entry(
        self,
        src_ip: str,
        dst_ip: str,
        protonum: int = 6,
        timeout: int = 0,
        mark: str = "",
    ) -> None:
        cmd = f"-I -s {src_ip} -d {dst_ip} --protonum {str(protonum)}"

        if timeout > 0:
            cmd += f" --timeout {str(timeout)}"
        if mark:
            cmd += f" --mark {mark}"

        self.run(
            cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to create conntrack entry",
        )

    def update_entry(
        self,
        mark: str = "",
    ) -> None:
        cmd = "-U"
        if mark:
            cmd += f" --mark {mark}"

        self.run(
            cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to update conntrack entry",
        )
