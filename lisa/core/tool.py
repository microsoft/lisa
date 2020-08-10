from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional, TypeVar

from lisa.util.executableResult import ExecutableResult
from lisa.util.process import Process

if TYPE_CHECKING:
    from lisa.core.node import Node

T = TypeVar("T")


class Tool(ABC):
    def __init__(self, node: Node) -> None:
        self.node: Node = node
        self._isInstalled: Optional[bool] = None
        self.initialize()

    def initialize(self) -> None:
        pass

    @property
    def dependentedTools(self) -> List[T]:
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
        result = self.node.execute(f'bash -c "command -v {self.command}"')
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
        for dependency in self.dependentedTools:
            self.node.getTool(dependency)
        result = self.installInternal()
        return result

    def runAsync(
        self,
        extraParameters: str = "",
        useBash: bool = False,
        noErrorLog: bool = False,
        cwd: pathlib.Path = None,
    ) -> Process:
        command = f"{self.command} {extraParameters}"
        result: ExecutableResult = self.node.execute(
            command, useBash, noErrorLog=noErrorLog, cwd=cwd
        )
        return result

    def run(
        self,
        extraParameters: str = "",
        useBash: bool = False,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
        cwd: pathlib.Path = None,
    ) -> ExecutableResult:
        command = f"{self.command} {extraParameters}"
        result: ExecutableResult = self.node.execute(
            command, useBash, noErrorLog=noErrorLog, noInfoLog=noInfoLog, cwd=cwd
        )
        return result


class ExecutableException(Exception):
    def __init__(self, exe: Tool, message: str):
        self.message = f"{exe.command}: {message}"
