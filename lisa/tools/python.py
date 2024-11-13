# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import PurePath
from typing import TYPE_CHECKING, List, Type

from assertpy import assert_that

from lisa.executable import Tool

if TYPE_CHECKING:
    from lisa.node import Node

from lisa.operating_system import BSD, Posix
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

    def get_python_path(self, sudo: bool = False) -> str:
        return self.run(
            '-c "import sys; print(' + "':'" + '.join([x for x in sys.path if x]))"',
            expected_exit_code=0,
            expected_exit_code_failure_message=("Could not fetch python sys.path!"),
            shell=True,
            sudo=sudo,
        ).stdout


class Pip(Tool):
    _no_permission_pattern = re.compile(r"Permission denied", re.M)
    _option_b_pattern = re.compile(r"no such option: -b", re.M)

    @property
    def command(self) -> str:
        if isinstance(self.node.os, BSD):
            return "pip"
        return "pip3"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Python]

    def _install(self) -> bool:
        package_name = "python3-pip"
        if isinstance(self.node.os, BSD):
            package_name = "devel/py-pip"
        assert isinstance(self.node.os, Posix)
        self.node.os.install_packages(package_name)
        return self._check_exists()

    def install_packages(
        self, packages_name: str, install_path: str = "", install_to_user: bool = False
    ) -> None:
        node = self.node
        if not install_to_user:
            cmd_line = f"install -q {packages_name}"
        else:
            cmd_line = f"install --user -q {packages_name}"

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


class PythonVenv(Tool):
    @property
    def command(self) -> str:
        path = self.get_venv_path() / "bin" / self._python.command
        return str(path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Python]

    def __init__(self, node: "Node", venv_path: str) -> None:
        super().__init__(node)
        self._python: Python = self.node.tools[Python]
        self._venv_installation_path = venv_path

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("python3-venv")
        return self._check_exists()

    def get_venv_path(self) -> PurePath:
        if not hasattr(self, "_venv_path"):
            self._venv_path = self._create_venv(self._venv_installation_path)
        return self._venv_path

    def install_packages(self, packages_name: str) -> None:
        venv_path = self.get_venv_path()
        cache_dir = venv_path.joinpath("cache")
        self.node.tools[Mkdir].create_directory(str(cache_dir))
        envs = {"TMPDIR": str(cache_dir)}
        cmd_result = self.run(
            f"-m pip install -q {packages_name} --cache-dir={cache_dir}",
            force_run=True,
            update_envs=envs,
        )
        assert_that(
            cmd_result.exit_code, f"fail to install {packages_name}"
        ).is_equal_to(0)

    def exists_package(self, package_name: str) -> bool:
        result = self.run(f"-m pip show {package_name}")
        return result.exit_code == 0

    def uninstall_package(self, package_name: str) -> bool:
        result = self.run(f"-m pip uninstall {package_name} -y", force_run=True)
        return result.exit_code == 0

    def delete_venv(self) -> None:
        if hasattr(self, "_venv_path"):
            self.node.execute(f"rm -rf {self._venv_path}")
            delattr(self, "_venv_path")
        else:
            self._log.info("venv path not found, nothing to delete")

    def _create_venv(self, venv_path: str) -> PurePath:
        cmd_result = self._python.run(
            f"-m venv {venv_path}", force_run=True, shell=True
        )
        assert_that(
            cmd_result.exit_code, f"fail to create venv: {venv_path}"
        ).is_equal_to(0)
        self._venv_path = self.node.get_pure_path(venv_path)
        return self._venv_path

    def _check_exists(self) -> bool:
        venv = self._python.run("-m venv --help", force_run=True)
        ensurepip = self._python.run("-m ensurepip", force_run=True)
        return (
            venv.exit_code == 0 and "No module named ensurepip" not in ensurepip.stdout
        )
