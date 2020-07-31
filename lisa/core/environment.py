from .node import Node
from .platform import Platform


class Environment:
    def __init__(self):
        self.platform: Platform = None
        self.nodes: [Node] = None

    def setPlatform(self, platform: Platform):
        self.platform = platform

    def setNodes(self, nodes):
        self.nodes = nodes
