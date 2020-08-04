import copy
from lisa import log
from lisa.core.nodeFactory import NodeFactory
from .node import Node
from lisa import constants


class Environment(object):
    CONFIG_NODES = "nodes"
    CONFIG_TEMPLATE = "template"
    CONFIG_TEMPLATE_NODE_COUNT = "nodeCount"

    def __init__(self):
        self.nodes: list[Node] = []
        self.platform = None
        self.spec = None

    @staticmethod
    def loadEnvironment(config):
        environment = Environment()
        spec = copy.deepcopy(config)

        has_default_node = False
        nodes_spec = []
        node_config = spec.get(Environment.CONFIG_NODES)
        if node_config is not None:
            for node_config in config.get(Environment.CONFIG_NODES):
                node = NodeFactory.createNodeFromConfig(node_config)
                if node is not None:
                    environment.nodes.append(node)
                else:
                    nodes_spec.append(node_config)

                has_default_node = environment._validateSingleDefault(
                    has_default_node, node_config.get(constants.IS_DEFAULT)
                )

        # validate template and node not appear together
        nodes_template = spec.get(Environment.CONFIG_TEMPLATE)
        if nodes_template is not None:
            for item in nodes_template:

                node_count = item.get(Environment.CONFIG_TEMPLATE_NODE_COUNT)
                if node_count is None:
                    node_count = 1
                else:
                    del item[Environment.CONFIG_TEMPLATE_NODE_COUNT]

                is_default = item.get(constants.IS_DEFAULT)
                has_default_node = environment._validateSingleDefault(
                    has_default_node, is_default
                )
                for index in range(node_count):
                    copied_item = copy.deepcopy(item)
                    # only one default node for template also
                    if is_default is True and index > 0:
                        del copied_item[constants.IS_DEFAULT]
                    nodes_spec.append(copied_item)
            del spec[Environment.CONFIG_TEMPLATE]

        if len(nodes_spec) == 0 and len(environment.nodes) == 0:
            raise Exception("not found any node in environment")

        spec[Environment.CONFIG_NODES] = nodes_spec

        environment.spec = spec
        log.debug("environment spec is %s", environment.spec)
        return environment

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

    def _validateSingleDefault(self, has_default, is_default):
        if is_default is True:
            if has_default is True:
                raise Exception("only one node can set isDefault to True")
            has_default = True
        return has_default
