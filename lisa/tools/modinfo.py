# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any

from lisa.executable import Tool
from lisa.util import find_patterns_in_lines


class Modinfo(Tool):
    __version_pattern = re.compile(r"^version:[ \t]*([^ \n]*)")

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "modinfo"

    def get_info(
        self,
        mod_name: str,
        force_run: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
    ) -> str:
        result = self.run(
            mod_name,
            sudo=True,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Modinfo failed for module {mod_name}",
        )
        return result.stdout

    def get_version(
        self,
        mod_name: str,
        force_run: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
    ) -> str:
        output = self.get_info(
            mod_name=mod_name,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
        )
        found_version = find_patterns_in_lines(output, [self.__version_pattern])
        return found_version[0][0] if found_version[0] else ""
