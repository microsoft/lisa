from __future__ import annotations

import copy
from collections import UserDict
from functools import partial
from typing import TYPE_CHECKING, Optional

from lisa import schema
from lisa.node import Nodes
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
        self.data: Optional[schema.Environment] = None

        self._default_node: Optional[Node] = None
        self._log = get_logger("env", self.name)

    @staticmethod
    def load(environment_data: schema.Environment) -> Environment:
        environment = Environment()
        environment.name = environment_data.name

        has_default_node = False
        nodes_spec = []
        if environment_data.nodes:
            for node_data in environment_data.nodes:
                node = environment.nodes.from_data(node_data)
                if not node:
                    # it's a spec
                    nodes_spec.append(node_data)

                has_default_node = environment._validate_single_default(
                    has_default_node, node_data.is_default
                )

        # validate template and node not appear together
        if environment_data.template is not None:
            is_default = environment_data.template.is_default
            has_default_node = environment._validate_single_default(
                has_default_node, is_default
            )
            for i in range(environment_data.template.node_count):
                copied_item = copy.deepcopy(environment_data.template)
                # only one default node for template also
                if is_default and i > 0:
                    copied_item.is_default = False
                nodes_spec.append(copied_item)
            environment_data.template = None

        if len(nodes_spec) == 0 and len(environment.nodes) == 0:
            raise LisaException("not found any node in environment")

        environment_data.nodes = nodes_spec

        environment.data = environment_data
        environment._log.debug(f"environment data is {environment.data}")
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


def load_environments(environment_root_data: Optional[schema.EnvironmentRoot]) -> None:
    if not environment_root_data:
        return
    environments.max_concurrency = environment_root_data.max_concurrency
    environments_data = environment_root_data.environments
    without_name: bool = False
    log = _get_init_logger()
    for environment_data in environments_data:
        environment = Environment.load(environment_data)
        if not environment.name:
            if without_name:
                raise LisaException("at least two environments has no name")
            environment.name = _default_no_name
            without_name = True
        log.info(f"loaded environment {environment.name}")
        environments[environment.name] = environment


if TYPE_CHECKING:
    EnvironmentsDict = UserDict[str, Environment]
else:
    EnvironmentsDict = UserDict


class Environments(EnvironmentsDict):
    def __init__(self) -> None:
        super().__init__()
        self.max_concurrency: int = 1

    def __getitem__(self, k: Optional[str] = None) -> Environment:
        if k is None:
            key = _default_no_name
        else:
            key = k.lower()
        environment = self.data.get(key)
        if environment is None:
            raise LisaException(f"not found environment '{k}'")

        return environment

    def __setitem__(self, k: str, v: Environment) -> None:
        self.data[k] = v

    @property
    def default(self) -> Environment:
        return self[_default_no_name]


environments = Environments()
