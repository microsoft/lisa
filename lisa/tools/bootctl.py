# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.util import UnsupportedDistroException


class BootCtl(Tool):
    @property
    def command(self) -> str:
        return "bootctl"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages("systemd-udev")
        else:
            raise UnsupportedDistroException(
                self.node.os,
                f"tool {self.command} can't be installed in {self.node.os.name}",
            )
        return self._check_exists()

    def get_esp_path(self) -> str:
        return self._get_cmd_output("--print-esp-path")

    def get_boot_path(self) -> str:
        return self._get_cmd_output("--print-boot-path")

    def get_root_device(self) -> str:
        return self._get_cmd_output("--print-root-device")

    def _get_cmd_output(self, cmd: str) -> str:
        cmd_result = self.run(
            cmd,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to get ESP path",
            shell=True,
            sudo=True,
            force_run=True,
        )
        return cmd_result.stdout
