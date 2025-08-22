# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, cast

from retry import retry

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException

from .gcc import Gcc
from .git import Git


class Ntpstat(Tool):
    repo = "https://github.com/darkhelmet/ntpstat"
    __not_sync = "unsynchronised"

    @property
    def command(self) -> str:
        return self._command

    @property
    def can_install(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "ntpstat"

    def _install_from_src(self) -> None:
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        gcc = self.node.tools[Gcc]
        code_path = tool_path.joinpath("ntpstat")
        gcc.compile(f"{code_path}/ntpstat.c", "ntpstat")
        self._command = "./ntpstat"

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("ntpstat")
        if not self._check_exists():
            self._install_from_src()
        return self._check_exists()

    @retry(exceptions=LisaException, tries=40, delay=0.5)  # type: ignore
    def check_time_sync(self) -> None:
        cmd_result = self.run(shell=True, sudo=True, force_run=True)
        if self.__not_sync in cmd_result.stdout:
            raise LisaException("Local time is not synced with time server.")
