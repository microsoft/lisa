# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import re
from pathlib import PurePath
from typing import Any, List, Optional, Type, cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix, Ubuntu
from lisa.tools.curl import Curl
from lisa.tools.echo import Echo
from lisa.tools.gcc import Gcc
from lisa.tools.ln import Ln
from lisa.tools.rm import Rm
from lisa.util import LisaException, UnsupportedDistroException
from lisa.util.process import ExecutableResult


class Cargo(Tool):
    # cargo 1.67.1 (8ecd4f20a 2023-01-10)
    _version_pattern = re.compile(
        r"cargo (?P<major>\d+).(?P<minor>(\d+)).(?P<patch>(\d+)) ",
        re.M,
    )

    # stable-x86_64-unknown-linux-gnu (default)
    _rust_toolchain_pattern = re.compile(
        r"\w+-\w+-\w+-\w+-\w+",
        re.M,
    )
    toolchain: str = ""

    @property
    def command(self) -> str:
        return self._command

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Gcc]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "cargo"

    def _install(self) -> bool:
        node_os = self.node.os
        cargo_source_url = "https://sh.rustup.rs"
        if isinstance(node_os, CBLMariner) or isinstance(node_os, Ubuntu):
            self.__install_dependencies()

            # install cargo/rust
            curl = self.node.tools[Curl]
            result = curl.fetch(
                arg="-sSf",
                url=cargo_source_url,
                execute_arg="-s -- -y",
                shell=True,
            )
            result.assert_exit_code()

            echo = self.node.tools[Echo]
            home_dir = echo.run(
                "$HOME",
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="failure to grab $HOME path",
            ).stdout

            ln = self.node.tools[Ln]
            ln.create_link(
                is_symbolic=True,
                target=f"{home_dir}/.cargo/bin/cargo",
                link="/usr/local/bin/cargo",
            )
            ln.create_link(
                is_symbolic=True,
                target=f"{home_dir}/.cargo/bin/rustup",
                link="/usr/local/bin/rustup",
            )
        else:
            raise UnsupportedDistroException(node_os)
        is_installed = self._check_exists()

        # Point cargo from stable toolchain of rust after installation
        if is_installed:
            self.node.execute("rustup default stable", shell=True)
            self.toolchain = self.__get_rust_toolchain()
            self._log.debug(f"Rust toolchain: {self.toolchain}")
            self._command = f"{home_dir}/.rustup/toolchains/{self.toolchain}/bin/cargo"

        self.node.tools[Rm].remove_file(
            "/usr/local/bin/cargo",
            sudo=True,
        )
        self.node.tools[Rm].remove_file(
            "/usr/local/bin/rustup",
            sudo=True,
        )
        return is_installed

    def __install_dependencies(self) -> None:
        node_os: Posix = cast(Posix, self.node.os)

        # install prerequisites
        node_os.install_packages(["build-essential", "cmake"])

        gcc = self.node.tools[Gcc]
        gcc_version_info = gcc.get_version()
        self.node.log.debug(f"Gcc Version: {gcc_version_info}")

        curl = self.node.tools[Curl]
        curl_version_info = curl.get_version()
        self.node.log.debug(f"Curl Version: {curl_version_info}")

    def build(
        self,
        release: bool = True,
        features: str = "",
        sudo: bool = False,
        cwd: Optional[PurePath] = None,
    ) -> ExecutableResult:
        err_msg = "Cargo build failed"
        echo = self.node.tools[Echo]
        path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout

        if os.path.dirname(self._command) not in path:
            path = f"{os.path.dirname(self._command)}:{path}"

        command = "build"
        if release:
            command = f"{command} --release"
        if features:
            command = f"{command} --features={features}"
        result = self.run(
            command,
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
            sudo=sudo,
            cwd=cwd,
            update_envs={"PATH": path},
            shell=True,
        )
        return result

    def test(
        self,
        sudo: bool = False,
        cwd: Optional[PurePath] = None,
        expected_exit_code: Optional[int] = None,
    ) -> ExecutableResult:
        echo = self.node.tools[Echo]
        path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout

        if os.path.dirname(self._command) not in path:
            path = f"{os.path.dirname(self._command)}:{path}"

        result = self.run(
            "-v test",
            sudo=sudo,
            cwd=cwd,
            update_envs={"PATH": path},
            shell=True,
            expected_exit_code=expected_exit_code,
            expected_exit_code_failure_message="cargo test failed",
        )
        return result

    def __get_rust_toolchain(
        self,
        sudo: bool = False,
        shell: bool = False,
        cwd: Optional[PurePath] = None,
    ) -> str:
        err_msg = "Error occurred in getting rust toolchain info"
        output = self.node.execute(
            "rustup default",
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
            sudo=sudo,
            cwd=cwd,
            shell=shell,
        ).stdout

        matched_toolchain = self._rust_toolchain_pattern.match(output)
        if matched_toolchain:
            return matched_toolchain.group(0)
        raise LisaException("fail to get rust toolchain")
