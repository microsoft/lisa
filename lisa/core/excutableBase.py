from abc import ABC

from lisa import Node


class ExecutableBase(ABC):
    def __init__(self) -> None:
        self.node = None

    def assignNode(self, node: Node) -> None:
        if self.node is not None:
            raise Exception("Node is assigned, cannot be assigned again")
        self.node = node

    def getCommand(self) -> str:
        return ""

    def run(self, extraParameters: str) -> None:
        pass

    def canInstall(self) -> bool:
        raise NotImplementedError()

    def install(self) -> None:
        pass

    def installed(self) -> bool:
        return False
