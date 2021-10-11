# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any

from lisa.executable import Tool
from lisa.util import LisaException, find_patterns_in_lines


class Lsmod(Tool):
    # The output of lsmod command is in below format -
    #   Module                  Size  Used by
    #    fuse                   52176  3
    #   cryptd                 14125  0
    #   aes_generic            32970  1 aes_i586
    __output_pattern = re.compile(
        r"^(?P<name>[^\s]+)\s+(?P<size>[^\s]+)\s+(?P<usedby>.*)?$", re.MULTILINE
    )

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "lsmod"

    def module_exists(
        self,
        mod_name: str = "",
        force_run: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
    ) -> bool:
        result = self.run(
            sudo=True,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
        )
        if result.exit_code != 0:
            raise LisaException(
                f"{self._command} command got non-zero exit code: {result.exit_code}"
            )

        module_info = find_patterns_in_lines(result.stdout, [self.__output_pattern])
        if any(mod_name in info for sublist in module_info for info in sublist):
            return True

        return False
