# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException, UnsupportedDistroException


class Mokutil(Tool):
    @property
    def command(self) -> str:
        return "mokutil"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        try:
            posix_os.install_packages([self])
        except Exception as e:
            raise UnsupportedDistroException(
                self.node.os,
                "Failed to install mokutil.",
            ) from e
        return self._check_exists()

    def is_secure_boot_enabled(self) -> bool:
        if not self.node.shell.exists(self.node.get_pure_path("/sys/firmware/efi")):
            return False

        # mokutil --sb-state returns:
        #   "SecureBoot enabled" or "SecureBoot disabled"
        cmd_result = self.run(
            "--sb-state",
            force_run=True,
            sudo=True,
        )
        cmd_result.assert_exit_code(
            0, "Failed to query Secure Boot state", include_output=True
        )
        if "SecureBoot enabled" in cmd_result.stdout:
            return True
        if "SecureBoot disabled" in cmd_result.stdout:
            return False
        raise LisaException(
            f"Unrecognized Secure Boot state: {cmd_result.stdout}\n{cmd_result.stderr}"
        )
