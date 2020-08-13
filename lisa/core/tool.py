from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional, Type

from lisa.util.executableResult import ExecutableResult
from lisa.util.process import Process

if TYPE_CHECKING:
    from lisa.core.node import Node


class Tool(ABC):
    def __init__(self, node: Node) -> None:
        self.node: Node = node
        self.initialize()

        self._isInstalled: Optional[bool] = None

    def initialize(self) -> None:
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def dependencies(self) -> List[Type[Tool]]:
        """
        declare all dependencies here
        they can be batch check and installed.
        """
        return []

    @property
    @abstractmethod
    def command(self) -> str:
        raise NotImplementedError()

    @property
    @abstractmethod
    def can_install(self) -> bool:
        raise NotImplementedError()

    @property
    def _is_installed_internal(self) -> bool:
        if self.node.is_linux:
            where_command = "command -v"
        else:
            where_command = "where"
        result = self.node.execute(
            f"{where_command} {self.command}", shell=True, no_info_log=True
        )
        self._isInstalled = result.exit_code == 0
        return self._isInstalled

    @property
    def is_installed(self) -> bool:
        # the check may need extra cost, so cache it's result.
        if self._isInstalled is None:
            self._isInstalled = self._is_installed_internal
        return self._isInstalled

    def _install_internal(self) -> bool:
        raise NotImplementedError()

    def install(self) -> bool:
        # check dependencies
        for dependency in self.dependencies:
            self.node.get_tool(dependency)
        result = self._install_internal()
        return result

    def runasync(
        self,
        parameters: str = "",
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        command = f"{self.command} {parameters}"
        process = self.node.executeasync(
            command, shell, no_error_log=no_error_log, cwd=cwd, no_info_log=no_info_log,
        )
        return process

    def run(
        self,
        parameters: str = "",
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        process = self.runasync(
            parameters=parameters,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result()
