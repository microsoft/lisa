from typing import Dict, Optional

from lisa.common.logger import log
from lisa.util import constants

from .node import Node


class NodeFactory:
    @staticmethod
    def createNodeFromConfig(config: Dict[str, object]) -> Optional[Node]:
        node_type = config.get(constants.TYPE)
        node = None
        if node_type is None:
            raise Exception("type of node shouldn't be None")
        if node_type in [
            constants.ENVIRONMENTS_NODES_LOCAL,
            constants.ENVIRONMENTS_NODES_REMOTE,
        ]:
            is_default = NodeFactory._isDefault(config)
            node = Node.createNode(node_type=node_type, isDefault=is_default)
        if node is not None:
            log.debug("created node '%s'", node_type)
        return node

    @staticmethod
    def createNodeFromSpec(
        spec: Dict[str, object], node_type: str = constants.ENVIRONMENTS_NODES_REMOTE
    ) -> Node:
        is_default = NodeFactory._isDefault(spec)
        node = Node.createNode(spec=spec, node_type=node_type, isDefault=is_default)
        return node

    @staticmethod
    def _isDefault(config: Dict[str, object]) -> bool:
        default = config.get(constants.IS_DEFAULT)
        if default is not None and default is True:
            default = True
        else:
            default = False
        return default
