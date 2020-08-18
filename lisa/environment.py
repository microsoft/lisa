from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Dict, List, Optional, cast

from lisa.node import from_config
from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.platform_ import Platform


_default_no_name = "_no_name_default"
_all_environments: Dict[str, Environment] = dict()

max_concurrency = 1


class Environment(object):
    def __init__(self) -> None:
        self.nodes: List[Node] = []
        self.name: str = ""
        self.is_ready: bool = False
        self.platform: Optional[Platform] = None
        self.spec: Optional[Dict[str, object]] = None

        self._default_node: Optional[Node] = None
        self._log = get_logger("env", self.name)

    @staticmethod
    def load(config: Dict[str, object]) -> Environment:
        environment = Environment()
        spec = copy.deepcopy(config)

        environment.name = cast(str, spec.get(constants.NAME, ""))

        has_default_node = False
        nodes_spec = []
        nodes_config = cast(
            List[Dict[str, object]], spec.get(constants.ENVIRONMENTS_NODES)
        )
        for node_config in nodes_config:
            index = str(len(environment.nodes))
            node = from_config(index, node_config)
            if node is not None:
                environment.nodes.append(node)
            else:
                nodes_spec.append(node_config)

            is_default = cast(Optional[bool], node_config.get(constants.IS_DEFAULT))
            has_default_node = environment._validate_single_default(
                has_default_node, is_default
            )

        # validate template and node not appear together
        nodes_template = cast(
            List[Dict[str, object]], spec.get(constants.ENVIRONMENTS_TEMPLATE)
        )
        if nodes_template is not None:
            for item in nodes_template:
                node_count = cast(
                    Optional[int], item.get(constants.ENVIRONMENTS_TEMPLATE_NODE_COUNT)
                )
                if node_count is None:
                    node_count = 1
                else:
                    del item[constants.ENVIRONMENTS_TEMPLATE_NODE_COUNT]

                is_default = cast(Optional[bool], item.get(constants.IS_DEFAULT))
                has_default_node = environment._validate_single_default(
                    has_default_node, is_default
                )
                for i in range(node_count):
                    copied_item = copy.deepcopy(item)
                    # only one default node for template also
                    if is_default and i > 0:
                        del copied_item[constants.IS_DEFAULT]
                    nodes_spec.append(copied_item)
            del spec[constants.ENVIRONMENTS_TEMPLATE]

        if len(nodes_spec) == 0 and len(environment.nodes) == 0:
            raise LisaException("not found any node in environment")

        spec[constants.ENVIRONMENTS_NODES] = nodes_spec

        environment.spec = spec
        environment._log.debug(f"environment spec is {environment.spec}")
        return environment

    @property
    def default_node(self) -> Node:
        if self._default_node is None:
            default = None
            for node in self.nodes:
                if node.is_default:
                    default = node
                    break
            if default is None:
                if len(self.nodes) == 0:
                    raise LisaException("No node found in current environment")
                else:
                    default = self.nodes[0]
            self._default_node = default
        return self._default_node

    def get_node_byname(self, name: str, throw_error: bool = True) -> Optional[Node]:
        found = None

        if len(self.nodes) == 0:
            raise LisaException("nodes shouldn't be Empty when call getNodeByName")

        for node in self.nodes:
            if node.name == name:
                found = node
                break
        if found is None and throw_error:
            raise LisaException(f"cannot find node {name}")
        return found

    def get_node_byindex(self, index: int) -> Node:
        found = None
        if self.nodes is not None:
            if len(self.nodes) > index:
                found = self.nodes[index]
        else:
            raise LisaException("nodes shouldn't be None when call getNodeByIndex")

        assert found
        return found

    def set_platform(self, platform: Platform) -> None:
        self.platform = platform

    def close(self) -> None:
        for node in self.nodes:
            node.close()

    def _validate_single_default(
        self, has_default: bool, is_default: Optional[bool]
    ) -> bool:
        if is_default:
            if has_default:
                raise LisaException("only one node can set isDefault to True")
            has_default = True
        return has_default


def load_environments(config: Dict[str, object]) -> None:
    if not config:
        raise LisaException("environment section must be set in config")
    global max_concurrency
    max_concurrency = cast(int, config.get(constants.ENVIRONMENT_MAX_CONCURRENCY, 1))
    environments_config = cast(
        List[Dict[str, object]], config.get(constants.ENVIRONMENTS)
    )
    without_name: bool = False
    log = get_logger("init", "env")
    for environment_config in environments_config:
        environment = Environment.load(environment_config)
        if not environment.name:
            if without_name:
                raise LisaException("at least two environments has no name")
            environment.name = _default_no_name
            without_name = True
        log.info(f"loaded environment {environment.name}")
        _all_environments[environment.name] = environment


def get_environments() -> Dict[str, Environment]:
    return _all_environments


def get_environment(name: Optional[str] = None) -> Environment:
    if name is None:
        key = _default_no_name
    else:
        key = name.lower()
    environment = _all_environments.get(key)
    if environment is None:
        raise LisaException(f"not found environment '{name}'")

    return environment
