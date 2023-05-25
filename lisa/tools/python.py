# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import List, Type

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools.mkdir import Mkdir
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

    def install_packages(self, packages_name: str, install_path: str = "") -> None:
        node = self.node
        cmd_line = f"install -q {packages_name}"

        envs = {}
        if install_path != "":
            tagert_path = install_path + "/python_packages"
            node.tools[Mkdir].create_directory(tagert_path)
            cache_path = install_path + "/tmp"
            node.tools[Mkdir].create_directory(cache_path)

            cmd_line += f" -t {tagert_path} --cache-dir={cache_path} -b {cache_path}"
            # Since Python 3.9, pip 21.2, -b for build path has been deprecated
            # Using TMPDIR/TMP/TEMP Env Variable instead
            envs = {"TMPDIR": cache_path}

        cmd_result = self.run(cmd_line, update_envs=envs)

        if 0 != cmd_result.exit_code and get_matched_str(
            cmd_result.stdout, self._no_permission_pattern
        ):
            cmd_result = self.run(cmd_line, update_envs=envs, sudo=True)

        assert_that(
            cmd_result.exit_code, f"fail to install {packages_name}"
        ).is_equal_to(0)

    def exists_package(self, package_name: str) -> bool:
        result = self.run(f"show {package_name}", force_run=True)
        return result.exit_code == 0
