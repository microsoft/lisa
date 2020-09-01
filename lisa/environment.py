from __future__ import annotations

import copy
from collections import UserDict
from functools import partial
from typing import TYPE_CHECKING, List, Optional

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
        self.requirements: Optional[List[schema.NodeSpace]] = None
        self._default_node: Optional[Node] = None
        self._log = get_logger("env", self.name)

    @staticmethod
    def load(env_runbook: schema.Environment) -> Environment:
        environment = Environment()
        environment.name = env_runbook.name

        has_default_node = False

        if not env_runbook.requirements and not env_runbook.nodes:
            raise LisaException("not found any node or requirement in environment")

        if env_runbook.nodes:
            for node_runbook in env_runbook.nodes:
                if isinstance(node_runbook, schema.LocalNode):
                    environment.nodes.from_local(node_runbook)
                else:
                    assert isinstance(
                        node_runbook, schema.RemoteNode
                    ), f"actual: {type(node_runbook)}"
                    environment.nodes.from_remote(node_runbook)

                has_default_node = environment.__validate_single_default(
                    has_default_node, node_runbook.is_default
                )

        environment.runbook = env_runbook
        environment.requirements = env_runbook.requirements
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
        cloned.requirements = copy.deepcopy(self.requirements)
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
