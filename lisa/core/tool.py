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
        self._isInstalled: Optional[bool] = None
        self.initialize()

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
    def canInstall(self) -> bool:
        raise NotImplementedError()

    @property
    def isInstalledInternal(self) -> bool:
        if self.node.isLinux:
            where_command = "command -v"
        else:
            where_command = "where"
        result = self.node.execute(
            f"{where_command} {self.command}", shell=True, noInfoLog=True
        )
        self._isInstalled = result.exitCode == 0
        return self._isInstalled

    @property
    def isInstalled(self) -> bool:
        # the check may need extra cost, so cache it's result.
        if self._isInstalled is None:
            self._isInstalled = self.isInstalledInternal
        return self._isInstalled

    def installInternal(self) -> bool:
        raise NotImplementedError()

    def install(self) -> bool:
        # check dependencies
        for dependency in self.dependencies:
            self.node.getTool(dependency)
        result = self.installInternal()
        return result

    def runAsync(
        self,
        extraParameters: str = "",
        shell: bool = False,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        command = f"{self.command} {extraParameters}"
        process = self.node.executeAsync(
            command, shell, noErrorLog=noErrorLog, cwd=cwd, noInfoLog=noInfoLog,
        )
        return process

    def run(
        self,
        extraParameters: str = "",
        shell: bool = False,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        process = self.runAsync(
            extraParameters=extraParameters,
            shell=shell,
            noErrorLog=noErrorLog,
            noInfoLog=noInfoLog,
            cwd=cwd,
        )
        return process.waitResult()


class ExecutableException(Exception):
    def __init__(self, exe: Tool, message: str):
        self.message = f"{exe.command}: {message}"
