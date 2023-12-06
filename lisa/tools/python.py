# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import PurePath
from typing import Any, List, Type

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
    _option_b_pattern = re.compile(r"no such option: -b", re.M)

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
            cmd_line += f" -t {tagert_path} --cache-dir={cache_path}"

            check_result = self.run("-b")
            if not get_matched_str(check_result.stdout, self._option_b_pattern):
                cmd_line += f" -b {cache_path}"

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

    def uninstall_package(self, package_name: str) -> bool:
        result = self.run(f"uninstall {package_name} -y", force_run=True, sudo=True)
        return result.exit_code == 0


class PythonVenv(Python):
    @property
    def command(self) -> str:
        return f"{self.get_venv_path()}/bin/{super().command}"

    def _check_exists(self) -> bool:
        # _super = type(super())
        # assert isinstance(super(), Python)
        return self.node.execute("python3 -m venv --help", shell=True).exit_code == 0
        # return self.node.execute("python3 -m venv --help").exit_code == 0

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

    def _install(self) -> bool:
        super()._install()
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("python3-venv")
        return self._check_exists()

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Python]

    # if get_venv_path is invoked before create_venv, it will create
    # a venv in the node working path
    def get_venv_path(self) -> PurePath:
        if not hasattr(self, "_venv_path"):
            self._venv_path = self.create_venv()
        return self._venv_path

    def create_venv(self, venv_path: str = "", sudo: bool = False) -> PurePath:
        _venv_path: PurePath = (
            PurePath(venv_path) if venv_path else self.node.working_path / "venv"
        )
        cmd_result = super().run(
            f"-m venv {_venv_path}", force_run=True, sudo=sudo, shell=True
        )
        assert_that(
            cmd_result.exit_code, f"fail to create venv: {_venv_path}"
        ).is_equal_to(0)
        self._venv_path = _venv_path
        return self._venv_path

    def install_packages(self, packages_name: str, sudo: bool = False) -> None:
        cmd_result = self.run(
            f"-m pip -q install {packages_name}", force_run=True, shell=True, sudo=sudo
        )
        assert_that(
            cmd_result.exit_code, f"fail to install {packages_name}"
        ).is_equal_to(0)

    def exists_package(self, package_name: str) -> bool:
        result = self.run(f"-m pip show {package_name}")
        return result.exit_code == 0

    def uninstall_package(self, package_name: str, sudo: bool = False) -> bool:
        result = self.run(
            f"-m pip uninstall {package_name} -y", force_run=True, sudo=sudo
        )
        return result.exit_code == 0
