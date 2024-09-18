# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import Optional, Type

from lisa.executable import Tool


class Sed(Tool):
    @property
    def command(self) -> str:
        return "sed"

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return SedBSD

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
        match_line: str = "",
        sudo: bool = False,
    ) -> None:
        # always force run, make sure it happens every time.
        text = text.replace('"', '\\"')
        if match_line:
            append_line = f"{match_line}"
        else:
            append_line = "$"
        result = self.run(
            f"-i.bak '{append_line}a{text}' {file}",
            force_run=True,
            no_error_log=True,
            no_info_log=True,
            sudo=sudo,
            shell=True,
        )
        result.assert_exit_code(message=result.stdout)

    def delete_lines(self, pattern: str, file: PurePath, sudo: bool = False) -> None:
        expression = f"/{pattern}/d"
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


class SedBSD(Sed):
    @property
    def command(self) -> str:
        return "gsed"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        self.node.os.install_packages("gsed")  # type: ignore
        return self._check_exists()
