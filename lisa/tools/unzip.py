# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException


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
        if result.exit_code != 0:
            raise LisaException(
                f"Failed to extract file to {dest_dir}, {result.stderr}"
            )
