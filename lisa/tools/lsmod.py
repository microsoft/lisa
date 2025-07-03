# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any, List, Tuple

from lisa.executable import Tool
from lisa.util import find_patterns_groups_in_lines, find_patterns_in_lines


class Lsmod(Tool):
    # The output of lsmod command is in below format -
    #   Module                  Size  Used by
    #    fuse                   52176  3
    #   cryptd                 14125  0
    #   aes_generic            32970  1 aes_i586
    #   ip_tables              32768  3 iptable_filter,iptable_security,iptable_nat
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
        no_debug_log: bool = False,
    ) -> bool:
        result = self.run(
            sudo=True,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
            no_debug_log=no_debug_log,
            expected_exit_code=0,
        )

        module_info = find_patterns_in_lines(result.stdout, [self.__output_pattern])
        if any(mod_name in info for sublist in module_info for info in sublist):
            return True

        return False

    def get_used_by_modules(
        self,
        mod_name: str,
        sudo: bool = True,
        force_run: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
        no_debug_log: bool = True,
    ) -> Tuple[int, str]:
        """
        Returns a list of modules that are using the given module name.
        """
        result = self.run(
            sudo=sudo,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
            no_debug_log=no_debug_log,
            expected_exit_code=0,
        )

        module_info = find_patterns_groups_in_lines(
            result.stdout, [self.__output_pattern]
        )

        target_module = next(
            (module for module in module_info[0] if module["name"] == mod_name), None
        )

        # If the module is not found or has no 'usedby' information,
        # return 0 and empty string
        if target_module is None or not target_module.get("usedby"):
            return 0, ""

        usedby_split = target_module["usedby"].split(maxsplit=1)
        usedby_count = int(usedby_split[0]) if usedby_split[0].isdigit() else 0
        usedby_modules = usedby_split[1] if len(usedby_split) > 1 else ""

        return usedby_count, usedby_modules

    def list_modules(self) -> List[str]:
        """
        List all loaded kernel modules.
        This method runs the `lsmod` command and parses its output to return
        a list of module names.

        It skips the header line and returns only the module names.
        :return: A list of loaded kernel module names.
        """
        result = self.run(sudo=True, force_run=True)
        module_info = find_patterns_in_lines(result.stdout, [self.__output_pattern])
        if not module_info:
            return []
        module_info[0] = module_info[0][1:]  # Skip the header line
        return [info[0] for sublist in module_info for info in sublist]
