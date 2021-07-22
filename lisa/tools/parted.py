# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Parted(Tool):
    @property
    def command(self) -> str:
        return "parted"

    @property
    def can_install(self) -> bool:
        return True

    def make_partition(
        self, disk_name: str, part_type: str, start: str, end: str
    ) -> None:
        cmd_result = self.run(
            f"-s -- {disk_name} mkpart {part_type} {start} {end}", shell=True, sudo=True
        )
        cmd_result.assert_exit_code()

    def make_label(self, disk_name: str, type: str = "gpt") -> None:
        cmd_result = self.run(
            f"-s -- {disk_name} mklabel {type}", shell=True, sudo=True
        )
        cmd_result.assert_exit_code()

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("parted")
        return self._check_exists()
