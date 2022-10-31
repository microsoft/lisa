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

    def move_file(self, src_path: str, dest_path: str, sudo: bool = False) -> None:
        self.run(f"{src_path} {dest_path}", sudo=sudo, force_run=True, shell=True)
