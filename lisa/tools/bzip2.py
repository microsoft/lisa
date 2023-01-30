# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa.executable import Tool
from lisa.operating_system import Posix


class Bzip2(Tool):
    @property
    def command(self) -> str:
        return "bzip2"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages([self])
        return self._check_exists()
