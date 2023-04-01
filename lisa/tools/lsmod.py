# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any, List, Union

from assertpy import assert_that

from lisa.executable import Tool
from lisa.util import find_patterns_in_lines


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

    def get_unloaded_modules(self, modules: Union[str, List[str]]) -> List[str]:
        if isinstance(modules, str):
            modules_list = modules.split(" ")
        else:
            modules_list = modules
        assert_that(modules_list).described_as(
            "Empty modules list passed to get_unloaded_modules in Lsmod tool"
        ).is_not_empty()

        result = self.run(sudo=True, force_run=True, expected_exit_code=0)
        minimized_list = []
        module_info = find_patterns_in_lines(result.stdout, [self.__output_pattern])

        for module in modules_list:
            # Don't add to minimized list if module is present in lsmod output
            if any(module in info for sublist in module_info for info in sublist):
                continue
            minimized_list.append(module)
        return minimized_list

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
            expected_exit_code=0,
        )

        module_info = find_patterns_in_lines(result.stdout, [self.__output_pattern])
        if any(mod_name in info for sublist in module_info for info in sublist):
            return True

        return False
