from typing import Any, Dict, Optional, cast

from lisa.core.node import Node
from lisa.util import constants
from lisa.util.exceptions import LisaException


class NodeFactory:
    @staticmethod
    def create_from_config(
        identifier: str, config: Dict[str, object]
    ) -> Optional[Node]:
        node_type = cast(str, config.get(constants.TYPE))
        node = None
        if node_type is None:
            raise LisaException("type of node shouldn't be None")
        if node_type in [
            constants.ENVIRONMENTS_NODES_LOCAL,
            constants.ENVIRONMENTS_NODES_REMOTE,
        ]:
            is_default = cast(bool, config.get(constants.IS_DEFAULT, False))
            node = Node.create(identifier, node_type=node_type, is_default=is_default)
            if node.is_remote:
                fields = [
                    constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS,
                    constants.ENVIRONMENTS_NODES_REMOTE_PORT,
                    constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS,
                    constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_PORT,
                    constants.ENVIRONMENTS_NODES_REMOTE_USERNAME,
                    constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD,
                    constants.ENVIRONMENTS_NODES_REMOTE_PRIVATEKEYFILE,
                ]
                parameters: Dict[str, Any] = dict()
                for key in config:
                    if key in fields:
                        parameters[key] = cast(str, config[key])
                node.set_connection_info(**parameters)
        return node

    @staticmethod
    def create_from_spec(
        spec: Dict[str, object], node_type: str = constants.ENVIRONMENTS_NODES_REMOTE
    ) -> Node:
        is_default = cast(bool, spec.get(constants.IS_DEFAULT, False))
        node = Node.create(
            "spec", spec=spec, node_type=node_type, is_default=is_default
        )
        return node
