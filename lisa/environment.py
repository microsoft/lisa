from __future__ import annotations

import copy
from functools import partial
from typing import TYPE_CHECKING, Dict, List, Optional, cast

from lisa.node import Nodes
from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.platform_ import Platform


_default_no_name = "_no_name_default"
_get_init_logger = partial(get_logger, "init", "env")


class Environment(object):
    def __init__(self) -> None:
        self.nodes: Nodes = Nodes()
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
            node = environment.nodes.create_by_config(node_config)
            if not node:
                # it's a spec
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
        return self.nodes.default

    def close(self) -> None:
        self.nodes.close()

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
    environments.max_concurrency = cast(
        int, config.get(constants.ENVIRONMENT_MAX_CONCURRENCY, 1)
    )
    environments_config = cast(
        List[Dict[str, object]], config.get(constants.ENVIRONMENTS)
    )
    without_name: bool = False
    log = _get_init_logger()
    for environment_config in environments_config:
        environment = Environment.load(environment_config)
        if not environment.name:
            if without_name:
                raise LisaException("at least two environments has no name")
            environment.name = _default_no_name
            without_name = True
        log.info(f"loaded environment {environment.name}")
        environments[environment.name] = environment


class Environments(Dict[str, Environment]):
    def __init__(self) -> None:
        self.max_concurrency = 1

    def __getitem__(self, k: Optional[str] = None) -> Environment:
        if k is None:
            key = _default_no_name
        else:
            key = k.lower()
        environment = super().get(key)
        if environment is None:
            raise LisaException(f"not found environment '{k}'")

        return environment

    @property
    def default(self) -> Environment:
        return self[_default_no_name]


environments = Environments()
