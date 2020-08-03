from abc import ABC
from lisa import Node


class ExecutableBase(ABC):
    def __init__(self):
        self.node = None

    def assignNode(self, node: Node):
        if self.node is not None:
            raise Exception("Node is assigned, cannot be assigned again")
        self.node = node

    def getCommand(self) -> str:
        pass

    def run(self, extraParameters: str) -> str:
        pass

    def canInstall(self):
        pass

    def install(self):
        pass

    def installed(self) -> bool:
        return False
