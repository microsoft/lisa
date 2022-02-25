# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List

from lisa.executable import Tool


class Ls(Tool):
    @property
    def command(self) -> str:
        return "ls"

    @property
    def can_install(self) -> bool:
        return False

    def path_exists(
        self, path: str, sudo: bool = False, force_run: bool = False
    ) -> bool:
        cmd_result = self.run(path, sudo=sudo, force_run=force_run)
        return 0 == cmd_result.exit_code

    def list_dir(self, path: str, sudo: bool = False) -> List[str]:
        cmd_result = self.node.execute(
            f"{self.command} -d {path}/*/",
            sudo=sudo,
            shell=True,
        )
        return cmd_result.stdout.split()
