from lisa import log, constants
from .node import Node


class NodeFactory:
    @staticmethod
    def createNodeFromConfig(config):
        node_type = config.get(constants.TYPE)
        node = None
        if node_type is None:
            raise Exception("type of node shouldn't be None")
        if node_type in [
            constants.ENVIRONMENT_NODES_LOCAL,
            constants.ENVIRONMENT_NODES_REMOTE,
        ]:
            is_default = NodeFactory._isDefault(config)
            node = Node.createNode(node_type=node_type, isDefault=is_default)
        if node is not None:
            log.debug("created node '%s'", node_type)
        return node

    @staticmethod
    def createNodeFromSpec(spec, node_type=constants.ENVIRONMENT_NODES_REMOTE):
        if node_type == Node.TYPE_REMOTE:
            isRemote = True
        elif node_type == Node.TYPE_LOCAL:
            isRemote = False
        else:
            raise Exception("unsupported node_type '%s'", node_type)
        node = Node.createNode(spec=spec, node_type=node_type, isRemote=isRemote)
        return node

    @staticmethod
    def _isDefault(config) -> bool:
        default = config.get(constants.IS_DEFAULT)
        if default is not None and default is True:
            default = True
        else:
            default = False
        return default
