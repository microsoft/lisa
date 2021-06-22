# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Mkfs(Tool):
    __EXIST_FILE_SYSTEM_PATTERN = re.compile(
        r".*appears to contain an existing filesystem", re.MULTILINE
    )

    @property
    def command(self) -> str:
        return "mkfs.xfs"

    @property
    def can_install(self) -> bool:
        return True

    # command - mkfs.xfs, mkfs.ext2, mkfs.ext3, mkfs.ext4
    def mkfs(self, disk: str, command: str) -> None:
        cmd_result = self.node.execute(
            f"echo y | {command} {disk}", shell=True, sudo=True
        )
        if self.__EXIST_FILE_SYSTEM_PATTERN.match(cmd_result.stdout):
            cmd_result = self.node.execute(
                f"echo y | {command} -f {disk}", shell=True, sudo=True
            )
        cmd_result.assert_exit_code()


class Mkfsxfs(Mkfs):
    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("xfsprogs")
        return self._check_exists()


class Mkfsext(Mkfs):
    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("e2fsprogs")
        return self._check_exists()
