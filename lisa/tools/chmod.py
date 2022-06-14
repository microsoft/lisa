# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Chmod(Tool):
    @property
    def command(self) -> str:
        return "chmod"

    def update_folder(self, path: str, permission: str, sudo: bool = False) -> None:
        self.run(f"-R {permission} {path}", sudo=sudo, force_run=True)
