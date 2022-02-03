# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from lisa.executable import Tool
from lisa.util import find_patterns_in_lines


class Sed(Tool):
    @property
    def command(self) -> str:
        return "sed"

    def substitute(
        self,
        regexp: str,
        replacement: str,
        file: str,
        match_lines: str = "",
        sudo: bool = False,
    ) -> None:
        # always force run, make sure it happens every time.
        if match_lines != "":
            expression = f"/{match_lines}/s/{regexp}/{replacement}/g"
        else:
            expression = f"s/{regexp}/{replacement}/g"
        expression = expression.replace('"', r"\"").replace("$", r"\$")

        cmd = f'-i.bak "{expression}" {file}'

        result = self.run(
            cmd,
            force_run=True,
            no_error_log=True,
            no_info_log=True,
            sudo=sudo,
            shell=True,
        )
        result.assert_exit_code(message=result.stdout)

    def append(
        self,
        text: str,
        file: str,
        sudo: bool = False,
    ) -> None:
        # always force run, make sure it happens every time.
        text = text.replace('"', '\\"')
        result = self.run(
            f"-i.bak '$a{text}' {file}",
            force_run=True,
            no_error_log=True,
            no_info_log=True,
            sudo=sudo,
            shell=True,
        )
        result.assert_exit_code(message=result.stdout)

    def substitute_or_append(
        self,
        is_substitute: bool = False,
        file_output: str = "",
        regexp: str = "",
        replacement: str = "",
        text: str = "",
        file: str = "",
        match_lines: str = "",
        sudo: bool = False,
    ) -> None:
        search_pattern = re.compile(rf"{regexp}", re.M)
        if is_substitute or find_patterns_in_lines(file_output, [search_pattern])[0]:
            self.substitute(regexp, replacement, file, match_lines, sudo)
        else:
            self.append(text, file, sudo)
