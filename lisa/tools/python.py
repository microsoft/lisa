# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import List, Type

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import UnsupportedDistroException, get_matched_str


class Python(Tool):
    @property
    def command(self) -> str:
        return "python3"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("python3")
        else:
            raise UnsupportedDistroException(self.node.os)

        return self._check_exists()


class Pip(Tool):
    _no_permission_pattern = re.compile(r"Permission denied", re.M)

    @property
    def command(self) -> str:
        return "pip3"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Python]

    def _install(self) -> bool:
        package_name = "python3-pip"
        assert isinstance(self.node.os, Posix)
        self.node.os.install_packages(package_name)
        return self._check_exists()

    def install_packages(self, packages_name: str) -> None:
        cmd_result = self.run(
            f"install -q {packages_name}",
        )
        if 0 != cmd_result.exit_code and get_matched_str(
            cmd_result.stdout, self._no_permission_pattern
        ):
            cmd_result = self.run(
                f"install -q {packages_name}",
                sudo=True,
            )
        assert_that(
            cmd_result.exit_code, f"fail to install {packages_name}"
        ).is_equal_to(0)

    def exists_package(self, package_name: str) -> bool:
        result = self.run(f"show {package_name}", force_run=True)
        return result.exit_code == 0
