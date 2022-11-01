# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Mv(Tool):
    @property
    def command(self) -> str:
        return "mv"

    @property
    def can_install(self) -> bool:
        return False

    def move(
        self, src_path: str, dest_path: str, overwrite: bool = False, sudo: bool = False
    ) -> None:
        args = "-f" if overwrite else ""
        self.run(
            f"{args} {src_path} {dest_path}",
            sudo=sudo,
            shell=True,
            force_run=True,
            expected_exit_code=0,
        )
