from __future__ import annotations

import copy
from collections import UserDict
from functools import partial
from typing import TYPE_CHECKING, Optional

from lisa import schema
from lisa.node import Nodes
from lisa.util import ContextMixin, LisaException
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.platform_ import Platform


_default_no_name = "_no_name_default"
_get_init_logger = partial(get_logger, "init", "env")


class Environment(ContextMixin):
    def __init__(self) -> None:
        self.nodes: Nodes = Nodes()
        self.name: str = ""
        self.is_ready: bool = False
        self.platform: Optional[Platform] = None
        self.runbook: Optional[schema.Environment] = None
        self._default_node: Optional[Node] = None
        self._log = get_logger("env", self.name)

    @staticmethod
    def load(environment_runbook: schema.Environment) -> Environment:
        environment = Environment()
        environment.name = environment_runbook.name

        has_default_node = False
        nodes_spec = []
        if environment_runbook.nodes:
            for node_runbook in environment_runbook.nodes:
                node = environment.nodes.from_runbook(node_runbook)
                if not node:
                    # it's a spec
                    nodes_spec.append(node_runbook)

                has_default_node = environment.__validate_single_default(
                    has_default_node, node_runbook.is_default
                )

        # validate template and node not appear together
        if environment_runbook.template is not None:
            is_default = environment_runbook.template.is_default
            has_default_node = environment.__validate_single_default(
                has_default_node, is_default
            )
            for i in range(environment_runbook.template.node_count):
                copied_item = copy.deepcopy(environment_runbook.template)
                # only one default node for template also
                if is_default and i > 0:
                    copied_item.is_default = False
                nodes_spec.append(copied_item)
            environment_runbook.template = None

        if len(nodes_spec) == 0 and len(environment.nodes) == 0:
            raise LisaException("not found any node in environment")

        environment_runbook.nodes = nodes_spec

        environment.runbook = environment_runbook
        environment._log.debug(f"environment data is {environment.runbook}")
        return environment

    @property
    def default_node(self) -> Node:
        return self.nodes.default

    def close(self) -> None:
        self.nodes.close()

    def clone(self) -> Environment:
        cloned = Environment()
        cloned.runbook = copy.deepcopy(self.runbook)
        cloned.nodes = self.nodes
        cloned.platform = self.platform
        cloned.name = f"inst_{self.name}"
        cloned._log = get_logger("env", self.name)
        return cloned

    def __validate_single_default(
        self, has_default: bool, is_default: Optional[bool]
    ) -> bool:
        if is_default:
            if has_default:
                raise LisaException("only one node can set isDefault to True")
            has_default = True
        return has_default


def load_environments(
    environment_root_runbook: Optional[schema.EnvironmentRoot],
) -> None:
    if not environment_root_runbook:
        return
    environments.max_concurrency = environment_root_runbook.max_concurrency
    environments_runbook = environment_root_runbook.environments
    without_name: bool = False
    log = _get_init_logger()
    for environment_runbook in environments_runbook:
        environment = Environment.load(environment_runbook)
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
