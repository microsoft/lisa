# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Fallocate(Tool):
    @property
    def command(self) -> str:
        return "fallocate"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        package_name = "util-linux"
        posix_os.install_packages(package_name)
        return self._check_exists()

    def create_file(self, length_in_bytes: int, file_path: str) -> None:
        self.run(
            f"-l {length_in_bytes} {file_path}",
            shell=True,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to create file by fallocate",
        )
