# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from typing import Optional, Type

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Mkdir, PowerShell


class Unzip(Tool):
    @property
    def command(self) -> str:
        return "unzip"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        assert isinstance(
            self.node.os, Posix
        ), f"unzip: unsupported OS {self.node.os.name}"
        self.node.os.install_packages(self.command)
        return self._check_exists()

    def extract(
        self,
        file: str,
        dest_dir: str,
        sudo: bool = False,
    ) -> None:
        # create folder when it doesn't exist
        self.node.execute(f"mkdir -p {dest_dir}", shell=True)
        result = self.run(
            f"{file} -d {dest_dir}", shell=True, force_run=True, sudo=sudo
        )
        result.assert_exit_code(
            0, f"Failed to extract file to {dest_dir}, {result.stderr}"
        )

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsUnzip


class WindowsUnzip(Unzip):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def extract(self, file: str, dest_dir: str, sudo: bool = False) -> None:
        self.node.tools[Mkdir].create_directory(dest_dir, sudo=sudo)
        self.node.tools[PowerShell].run_cmdlet(
            f"Expand-Archive -Path {file} -DestinationPath {dest_dir} -Force",
            sudo=sudo,
            fail_on_error=True,
        )
