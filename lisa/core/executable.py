from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from lisa.util.executableResult import ExecutableResult

if TYPE_CHECKING:
    from lisa.core.node import Node


class Executable(ABC):
    def __init__(self, node: Node) -> None:
        self.node: Node = node
        self.initialize()

    def initialize(self) -> None:
        pass

    @property
    @abstractmethod
    def command(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def canInstall(self) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def installed(self) -> bool:
        raise NotImplementedError()

    def install(self) -> None:
        pass

    def run(
        self, extraParameters: str = "", noErrorLog: bool = False
    ) -> ExecutableResult:
        command = f"{self.command} {extraParameters}"
        result: ExecutableResult = self.node.execute(command, noErrorLog)
        return result


class ExecutableException(Exception):
    def __init__(self, exe: Executable, message: str):
        self.message = f"{exe.command}: {message}"
