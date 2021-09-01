# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import TYPE_CHECKING, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Gcc
from lisa.tools.lscpu import Lscpu

if TYPE_CHECKING:
    from lisa.node import Node


class Make(Tool):
    def __init__(self, node: "Node") -> None:
        super().__init__(node)
        self._thread_count = 0

    @property
    def command(self) -> str:
        return "make"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages([self, Gcc])
        return self._check_exists()

    def make_install(self, cwd: PurePath, timeout: int = 600) -> None:
        self.make(arguments="", cwd=cwd, timeout=timeout)

        # install with sudo
        self.make(arguments="install", cwd=cwd, sudo=True, timeout=timeout)

    def make(
        self,
        arguments: str,
        cwd: PurePath,
        sudo: bool = False,
        timeout: int = 600,
        thread_count: int = 0,
    ) -> None:
        if thread_count == 0:
            if self._thread_count == 0:
                lscpu = self.node.tools[Lscpu]
                self._thread_count = lscpu.get_core_count()
            thread_count = self._thread_count

        # yes '' answers all questions with default value.
        result = self.node.execute(
            f"yes '' | make -j{self._thread_count} {arguments}",
            cwd=cwd,
            timeout=timeout,
            sudo=sudo,
            shell=True,
        )
        result.assert_exit_code()
