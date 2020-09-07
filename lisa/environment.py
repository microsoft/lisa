from __future__ import annotations

import copy
from collections import UserDict
from functools import partial
from typing import TYPE_CHECKING, Optional

from lisa import schema
from lisa.node import Nodes
from lisa.util import ContextMixin, InitializableMixin, LisaException
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.platform_ import Platform


_get_init_logger = partial(get_logger, "init", "env")


class Environment(ContextMixin, InitializableMixin):
    def __init__(self, warn_as_error: bool) -> None:
        super().__init__()

        self.nodes: Nodes = Nodes()
        self.name: str = ""

        self.is_ready: bool = False
        self.platform: Optional[Platform] = None
        # priority uses to plan order of request it.
        # cheaper env can be run earlier to run more cases.
        # 1. smaller is higher priority, it can be index of candidate environment
        # 2. -1 means not supported.
        self.priority: int = -1
        # original runbook which this environment supports
        self.runbook: schema.Environment
        self._capability: Optional[schema.EnvironmentSpace] = None
        self.warn_as_error = warn_as_error
        self._default_node: Optional[Node] = None
        self._log = get_logger("env", self.name)

    def _initialize(self) -> None:
        if not self.is_ready:
            raise LisaException("environment is not ready, cannot be initialized")
        # environment is ready, refresh latest capability
        self._capability = None
        self.nodes.initialize()

    @classmethod
    def from_runbook(
        cls, runbook: schema.Environment, warn_as_error: bool
    ) -> Environment:
        environment = Environment(warn_as_error)
        environment.name = runbook.name

        has_default_node = False

        if not runbook.nodes_requirement and not runbook.nodes:
            raise LisaException("not found any node or requirement in environment")

        if runbook.nodes:
            for node_runbook in runbook.nodes:
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
        environment.runbook = runbook
        return environment

    @property
    def default_node(self) -> Node:
        return self.nodes.default

    def close(self) -> None:
        self.nodes.close()

    def clone(self) -> Environment:
        cloned = Environment(self.warn_as_error)
        cloned.runbook = copy.deepcopy(self.runbook)
        cloned.nodes = self.nodes
        cloned.platform = self.platform
        cloned.name = f"inst_{self.name}"
        cloned._log = get_logger("env", self.name)
        return cloned

    @property
    def capability(self) -> schema.EnvironmentSpace:
        # merge existing node to capability
        if self._capability is None:
            result = schema.EnvironmentSpace(topology=self.runbook.topology)
            for node in self.nodes.list():
                result.nodes.append(node.capability)
            if not self.is_ready and self.runbook.nodes_requirement:
                result.nodes.extend(self.runbook.nodes_requirement)
            self._capability = result
        return self._capability

    def __validate_single_default(
        self, has_default: bool, is_default: Optional[bool]
    ) -> bool:
        if is_default:
            if has_default:
                raise LisaException("only one node can set isDefault to True")
            has_default = True
        return has_default


if TYPE_CHECKING:
    EnvironmentsDict = UserDict[str, Environment]
else:
    EnvironmentsDict = UserDict


class Environments(EnvironmentsDict):
    def __init__(
        self,
        warn_as_error: bool = False,
        max_concurrency: int = 1,
        allow_create: bool = True,
    ) -> None:
        super().__init__()
        self.warn_as_error = warn_as_error
        self.max_concurrency = max_concurrency
        self.allow_create = allow_create

    def get_or_create(
        self, requirement: schema.EnvironmentSpace
    ) -> Optional[Environment]:
        result: Optional[Environment] = None
        for environment in self.values():
            # find exact match, or create a new one.
            if requirement == environment.capability:
                result = environment
                break
        else:
            result = self.from_requirement(requirement)
        return result

    def from_requirement(
        self, requirement: schema.EnvironmentSpace
    ) -> Optional[Environment]:
        runbook = schema.Environment(
            topology=requirement.topology,
            nodes_requirement=requirement.nodes,
            capability=requirement,
        )
        log = _get_init_logger()
        log.debug(f"found new requirement: {requirement}")
        return self.from_runbook(runbook)

    def from_runbook(self, runbook: schema.Environment) -> Optional[Environment]:
        env: Optional[Environment] = None
        if self.allow_create:
            env = Environment.from_runbook(runbook, self.warn_as_error)
            if not env.name:
                env.name = f"req_{len(self.keys())}"
                runbook.name = env.name
            self[env.name] = env
            log = _get_init_logger()
            log.debug(f"create environment {env.name}: {env.runbook}")
        return env


def load_environments(root_runbook: Optional[schema.EnvironmentRoot],) -> Environments:
    if root_runbook:
        environments = Environments(
            warn_as_error=root_runbook.warn_as_error,
            max_concurrency=root_runbook.max_concurrency,
            allow_create=root_runbook.allow_create,
        )

        environments_runbook = root_runbook.environments
        for environment_runbook in environments_runbook:
            environment = Environment.from_runbook(
                environment_runbook, environments.warn_as_error
            )
            if not environment.name:
                environment.name = f"runbook_{len(environments)}"
            environments[environment.name] = environment
    else:
        environments = Environments()

    return environments
