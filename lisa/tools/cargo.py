# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import List, Optional, Type, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools.curl import Curl
from lisa.tools.echo import Echo
from lisa.tools.gcc import Gcc
from lisa.util.process import ExecutableResult


class Cargo(Tool):
    @property
    def command(self) -> str:
        return "cargo"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Gcc]

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        cargo_source_url = "https://sh.rustup.rs"
        try:
            # install prerequisites
            posix_os.install_packages(["build-essential", "cmake"])
            gcc = self.node.tools[Gcc]
            gcc_version_info = gcc.get_version().to_dict()
            self.node.log.info(f"Gcc Version: {gcc_version_info}")
            # install cargo/rust
            curl = self.node.tools[Curl]
            curl_version_info = curl.get_version().stdout
            self.node.log.info(f"Curl Version: {curl_version_info}")
            result = curl.fetch(
                arg="-sSf",
                url=cargo_source_url,
                execute_arg="-s -- -y",
                shell=True,
            )
            result.assert_exit_code()
        except Exception as e:
            self._log.debug(f"failed to install cargo: {e}")

        echo = self.node.tools[Echo]
        original_path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout
        new_path = f"$HOME/.cargo/bin:{original_path}"
        return self._check_exists(update_envs={"PATH": new_path})

    def build(
        self,
        sudo: bool = False,
        cwd: Optional[PurePath] = None,
    ) -> ExecutableResult:
        err_msg = "Cargo build failed"
        echo = self.node.tools[Echo]
        original_path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout
        new_path = f"$HOME/.cargo/bin:{original_path}"
        result = self.run(
            "build",
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
            sudo=sudo,
            cwd=cwd,
            update_envs={"PATH": new_path},
        )
        return result

    def test(
        self,
        sudo: bool = False,
        cwd: Optional[PurePath] = None,
    ) -> ExecutableResult:
        echo = self.node.tools[Echo]
        original_path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout
        new_path = f"$HOME/.cargo/bin:{original_path}"
        result = self.run(
            "test",
            sudo=sudo,
            cwd=cwd,
            update_envs={"PATH": new_path},
        )
        return result
