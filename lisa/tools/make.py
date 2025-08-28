# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import TYPE_CHECKING, Dict, List, Optional, Type, cast

from lisa.executable import Tool
from lisa.operating_system import BSD, Posix
from lisa.tools.gcc import Gcc
from lisa.tools.lscpu import Lscpu
from lisa.util.process import ExecutableResult

if TYPE_CHECKING:
    from lisa.node import Node


class Make(Tool):
    def __init__(self, node: "Node") -> None:
        super().__init__(node)
        self._thread_count = 0

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Gcc]

    @property
    def command(self) -> str:
        if isinstance(self.node.os, BSD):
            return "gmake"
        else:
            return "make"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages([self])
        return self._check_exists()

    def make_install(
        self,
        cwd: PurePath,
        arguments: str = "",
        timeout: int = 600,
        sudo: bool = True,
        update_envs: Optional[Dict[str, str]] = None,
    ) -> None:
        self.make(
            arguments=arguments,
            cwd=cwd,
            timeout=timeout,
            sudo=sudo,
            update_envs=update_envs,
        )

        # install with sudo
        self.make(
            arguments="install",
            cwd=cwd,
            timeout=timeout,
            sudo=sudo,
            update_envs=update_envs,
        )

    def make(
        self,
        arguments: str,
        cwd: PurePath,
        is_clean: bool = False,
        sudo: bool = False,
        timeout: int = 600,
        thread_count: int = 0,
        update_envs: Optional[Dict[str, str]] = None,
        ignore_error: bool = False,
    ) -> ExecutableResult:
        expected_exit_code: Optional[int] = 0
        if thread_count == 0:
            if self._thread_count == 0:
                lscpu = self.node.tools[Lscpu]
                self._thread_count = lscpu.get_thread_count()
            thread_count = self._thread_count

        if is_clean:
            self.run(
                "clean",
                cwd=cwd,
                sudo=sudo,
                shell=True,
                timeout=timeout,
                force_run=True,
                update_envs=update_envs,
            )

        if ignore_error:
            expected_exit_code = None
        # yes '' answers all questions with default value.
        result = self.node.execute(
            f"yes '' | make -j{thread_count} {arguments}",
            cwd=cwd,
            timeout=timeout,
            sudo=sudo,
            shell=True,
            update_envs=update_envs,
            expected_exit_code=expected_exit_code,
            expected_exit_code_failure_message="Failed to make",
        )
        return result
