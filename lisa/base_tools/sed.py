# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


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
        match_lines = match_lines.replace('"', '\\"')
        regexp = regexp.replace('"', '\\"')
        replacement = replacement.replace('"', '\\"')
        if match_lines != "":
            cmd = f'-i.bak "/{match_lines}/s/{regexp}/{replacement}/g" {file}'
        else:
            cmd = f'-i.bak "s/{regexp}/{replacement}/g" {file}'

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
