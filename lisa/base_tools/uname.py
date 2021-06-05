# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass

from lisa.executable import Tool
from lisa.util import LisaException


@dataclass
class UnameResult:
    has_result: bool
    uname_version: str = ""
    kernel_version: str = ""
    hardware_platform: str = ""
    operating_system: str = ""


class Uname(Tool):
    _key_info_pattern = re.compile(
        r"(?P<kernel_version>[^ ]*?) (?P<uname_version>[\w\W]*) (?P<platform>[\w\W]+?) "
        r"(?P<os>[\w\W]+?)$"
    )

    @property
    def command(self) -> str:
        return "uname"

    def _check_exists(self) -> bool:
        return True

    def get_linux_information(
        self, force_run: bool = False, no_error_log: bool = False
    ) -> UnameResult:
        self.initialize()
        cmd_result = self.run(
            "-vrio", force_run=force_run, no_error_log=no_error_log, no_info_log=True
        )

        if cmd_result.exit_code != 0:
            result = UnameResult(False, "", "", "", "")
        else:
            match_result = self._key_info_pattern.fullmatch(cmd_result.stdout)
            if not match_result:
                raise LisaException(f"no result matched, stdout: '{cmd_result.stdout}'")
            result = UnameResult(
                has_result=True,
                kernel_version=match_result.group("kernel_version"),
                uname_version=match_result.group("uname_version"),
                hardware_platform=match_result.group("platform"),
                operating_system=match_result.group("os"),
            )

        return result
