# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import PurePosixPath
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Fdisk
from lisa.util import LisaException


class Mount(Tool):
    __UMOUNT_ERROR_PATTERN = re.compile(r".*mountpoint not found", re.MULTILINE)

    @property
    def command(self) -> str:
        return "mount"

    @property
    def can_install(self) -> bool:
        return True

    def mount(self, disk_name: str, point: str) -> None:
        self.node.shell.mkdir(PurePosixPath(point), exist_ok=True)
        cmd_result = self.node.execute(
            f"mount {disk_name} {point}", shell=True, sudo=True
        )
        cmd_result.assert_exit_code()

    def umount(self, disk_name: str, point: str, erase: bool = True) -> None:
        cmd_result = self.node.execute(f"umount {point}", shell=True, sudo=True)
        if erase:
            fdisk = self.node.tools[Fdisk]
            fdisk.delete_partition(disk_name)
            self.node.execute(f"rm -r {point}", shell=True, sudo=True)
        if (
            not self.__UMOUNT_ERROR_PATTERN.match(cmd_result.stdout)
            and 0 != cmd_result.exit_code
        ):
            raise LisaException(f"Fail to run umount {point}.")

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("util-linux")
        return self._check_exists()
