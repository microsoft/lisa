# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Strace(Tool):
    @property
    def command(self) -> str:
        return "strace"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("strace")
        return self._check_exists()

    def get(self, command: str) -> str:
        return self.run(command, sudo=True, shell=True, force_run=True).stdout
