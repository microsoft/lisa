# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Tee(Tool):
    @property
    def command(self) -> str:
        return "tee"

    @property
    def can_install(self) -> bool:
        return self.node.os.is_posix

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        package_name = "coreutils"
        posix_os.install_packages(package_name)
        return self._check_exists()

    def write_to_file(
        self,
        value: str,
        file: PurePath,
        append: bool = False,
        sudo: bool = False,
    ) -> None:
        # tee breaks sudo ordering of tool.run()
        # cwd, shell, etc will be passed through to execute
        # sudo is the only one which needs special casing
        cmd = "tee"
        if append:
            cmd = f"{cmd} -a"
        if sudo:
            cmd = f"sudo {cmd}"
        cmd = f"{cmd} {str(file)}"
        self.node.execute(f"echo '{value}' | {cmd}", shell=True)
