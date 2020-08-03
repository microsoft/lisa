from .node import Node


class Environment:
    def __init__(self):
        self.nodes: list[Node] = None
        self.platform = None

    @property
    def defaultNode(self):
        default = None
        if self.nodes is not None:
            for node in self.nodes:
                if node.isDefault is True:
                    default = node
                    break
            if default is None:
                default = self.nodes[0]
        return default

    def getNodeByName(self, name: str, throwError=True):
        found = None
        if self.nodes is not None:
            for node in self.nodes:
                if node.name == name:
                    found = node
                    break
            if throwError:
                raise Exception("cannot find node %s" % (name))
        else:
            if throwError:
                raise Exception("nodes shouldn't be None when call getNode")
        return found

    def getNodeByIndex(self, index: int, throwError=True):
        found = None
        if self.nodes is not None:
            if len(self.nodes) > index:
                found = self.nodes[index]
        elif throwError:
            raise Exception("nodes shouldn't be None when call getNode")
        return found

    def setPlatform(self, platform):
        self.platform = platform

    def setNodes(self, nodes):
        self.nodes = nodes
