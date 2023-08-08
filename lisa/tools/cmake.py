# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import cast

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import Posix


class Cmake(Tool):
    @property
    def command(self) -> str:
        return "cmake"

    @property
    def can_install(self) -> bool:
        return self.node.is_posix

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("cmake")
        return self._check_exists()
