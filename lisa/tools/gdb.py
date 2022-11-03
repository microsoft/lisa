# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Gdb(Tool):
    @property
    def command(self) -> str:
        return "gdb"

    @property
    def can_install(self) -> bool:
        return True

    def debug(self, filename: str, arguments: str) -> str:
        output = self.run(f"{arguments} {filename}", shell=True, force_run=True)
        return output.stdout

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("gdb")
        return self._check_exists()
