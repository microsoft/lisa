# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import re
import shlex
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
    # Rustup mutates shared state under $HOME/.rustup. Baremetal jobs may reuse the
    # same account concurrently, so wait long enough for another toolchain install.
    RUSTUP_LOCK_TIMEOUT = 1800
    # The rustup installer downloads the full Rust toolchain. Baremetal lab
    # network throughput can be slow enough that the default command timeout is
    # too short even when the download is still making progress.
    RUSTUP_INSTALL_TIMEOUT = 1800

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

    def _check_exists(self) -> bool:
        exists, self._use_sudo = self.command_exists(self.command)
        if exists and self._cargo_runs(self.command):
            return True

        home_dir = self._get_home_dir()
        if not home_dir:
            return False

        cargo_bin = f"{home_dir}/.cargo/bin/cargo"
        if self._cargo_runs(cargo_bin):
            self._command = cargo_bin
            self._use_sudo = False
            rustup_bin = f"{home_dir}/.cargo/bin/rustup"
            self._try_set_toolchain(rustup_bin)
            return True

        return False

    def _install(self) -> bool:
        node_os = self.node.os
        cargo_source_url = "https://sh.rustup.rs"
        if isinstance(node_os, CBLMariner) or isinstance(node_os, Ubuntu):
            self.__install_dependencies()

            home_dir = self._get_home_dir()
            if not home_dir:
                raise LisaException("failure to grab $HOME path")
            cargo_bin = f"{home_dir}/.cargo/bin/cargo"
            rustup_bin = f"{home_dir}/.cargo/bin/rustup"

            # install cargo/rust
            curl = self.node.tools[Curl]
            install_command = (
                f"{shlex.quote(cargo_bin)} --version >/dev/null 2>&1 || "
                f"{shlex.quote(curl.command)} -sSf "
                f"{shlex.quote(cargo_source_url)} | sh -s -- -y"
            )
            self.node.execute(
                self.wrap_with_rustup_lock(install_command),
                shell=True,
                timeout=self.RUSTUP_INSTALL_TIMEOUT,
                expected_exit_code=0,
                expected_exit_code_failure_message="curl fetch failed",
            )

            ln = self.node.tools[Ln]
            ln.create_link(
                is_symbolic=True,
                target=cargo_bin,
                link="/usr/local/bin/cargo",
                force=True,
            )
            ln.create_link(
                is_symbolic=True,
                target=rustup_bin,
                link="/usr/local/bin/rustup",
                force=True,
            )
        else:
            raise UnsupportedDistroException(node_os)

        self.node.execute(
            self.wrap_with_rustup_lock(f"{shlex.quote(rustup_bin)} default stable"),
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to set rustup stable toolchain",
        )
        self.toolchain = self.__get_rust_toolchain(rustup_command=rustup_bin)
        self._log.debug(f"Rust toolchain: {self.toolchain}")
        self._command = cargo_bin
        self._exists = None
        is_installed = self._check_exists()

        self.node.tools[Rm].remove_file(
            "/usr/local/bin/cargo",
            sudo=True,
        )
        self.node.tools[Rm].remove_file(
            "/usr/local/bin/rustup",
            sudo=True,
        )
        return is_installed

    def wrap_with_rustup_lock(self, command: str) -> str:
        return (
            'mkdir -p "$HOME/.rustup" && '
            f"flock -w {self.RUSTUP_LOCK_TIMEOUT} "
            '"$HOME/.rustup/lisa-rustup.lock" '
            f"sh -c {shlex.quote(command)}"
        )

    def _get_home_dir(self) -> str:
        result = self.node.execute(
            "echo $HOME",
            shell=True,
            no_info_log=True,
            no_error_log=True,
            expected_exit_code=None,
        )
        if result.exit_code != 0:
            return ""
        return result.stdout.strip()

    def _cargo_runs(self, command: str) -> bool:
        result = self.node.execute(
            f"{shlex.quote(command)} --version",
            shell=True,
            no_info_log=True,
            no_error_log=True,
            expected_exit_code=None,
        )
        return result.exit_code == 0

    def _try_set_toolchain(self, rustup_command: str) -> None:
        result = self.node.execute(
            f"test -x {shlex.quote(rustup_command)}",
            shell=True,
            no_info_log=True,
            no_error_log=True,
            expected_exit_code=None,
        )
        if result.exit_code != 0:
            return
        try:
            self.toolchain = self.__get_rust_toolchain(rustup_command=rustup_command)
        except LisaException as identifier:
            self._log.debug(
                f"failed to detect rust toolchain from {rustup_command}: {identifier}"
            )

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
        rustup_command: str = "rustup",
        sudo: bool = False,
        shell: bool = False,
        cwd: Optional[PurePath] = None,
    ) -> str:
        err_msg = "Error occurred in getting rust toolchain info"
        output = self.node.execute(
            f"{shlex.quote(rustup_command)} default",
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
