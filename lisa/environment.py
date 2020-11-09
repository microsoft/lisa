from __future__ import annotations

import copy
from collections import UserDict
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, Any, List, Optional

from dataclasses_json import LetterCase, dataclass_json  # type: ignore
from marshmallow import validate

from lisa import schema, search_space
from lisa.node import Nodes
from lisa.util import ContextMixin, InitializableMixin, LisaException, constants
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.platform_ import Platform


_get_init_logger = partial(get_logger, "init", "env")


EnvironmentStatus = Enum(
    "EnvironmentStatus",
    [
        # just created, no operation
        "New",
        # prepared by platform, but may not be deployed
        "Prepared",
        # deployed, and platform says success
        "Deployed",
        # intialized and connected via SSH
        "Connected",
        # deleted by platform
        "Deleted",
    ],
)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class EnvironmentSpace(search_space.RequirementMixin):
    """
    Search space of an environment. It uses to
    1. Specify test suite requirement, see TestCaseRequirement
    2. Describe capability of an environment, see Environment.capability
    """

    topology: str = field(
        default=constants.ENVIRONMENTS_SUBNET,
        metadata=schema.metadata(
            validate=validate.OneOf([constants.ENVIRONMENTS_SUBNET])
        ),
    )
    nodes: List[schema.NodeSpace] = field(default_factory=list)

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        self._expand_node_space()

    def __eq__(self, o: object) -> bool:
        assert isinstance(o, EnvironmentSpace), f"actual: {type(o)}"
        return self.topology == o.topology and search_space.equal_list(
            self.nodes, o.nodes
        )

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(capability, EnvironmentSpace), f"actual: {type(capability)}"
        result = search_space.ResultReason()
        if not capability.nodes:
            result.add_reason("no node instance found")
        elif len(self.nodes) > len(capability.nodes):
            result.add_reason(
                f"no enough nodes, "
                f"capability: {len(capability.nodes)}, "
                f"requirement: {len(self.nodes)}"
            )
        else:
            if self.nodes:
                for index, current_req in enumerate(self.nodes):
                    current_cap = capability.nodes[index]
                    result.merge(
                        search_space.check(current_req, current_cap),
                        str(index),
                    )
                    if not result.result:
                        break

        return result

    def _generate_min_capability(self, capability: Any) -> Any:
        env = EnvironmentSpace(topology=self.topology)
        assert isinstance(capability, EnvironmentSpace), f"actual: {type(capability)}"
        assert capability.nodes
        for index, current_req in enumerate(self.nodes):
            if len(capability.nodes) == 1:
                current_cap = capability.nodes[0]
            else:
                current_cap = capability.nodes[index]

            env.nodes.append(current_req.generate_min_capability(current_cap))

        return env

    def _expand_node_space(self) -> None:
        if self.nodes:
            expanded_requirements: List[schema.NodeSpace] = []
            for node in self.nodes:
                expanded_requirements.extend(node.expand_by_node_count())
            self.nodes = expanded_requirements


class Environment(ContextMixin, InitializableMixin):
    def __init__(self, is_predefined: bool, warn_as_error: bool) -> None:
        super().__init__()

        self.nodes: Nodes = Nodes()
        self.name: str = ""

        self.status: EnvironmentStatus = EnvironmentStatus.New
        self.is_predefined: bool = is_predefined
        self.is_new: bool = True
        self.platform: Optional[Platform] = None
        # cost uses to plan order of environments.
        # cheaper env can fit cases earlier to run more cases on it.
        # 1. smaller is higher priority, it can be index of candidate environment
        # 2. 0 means no cost.
        self.cost: int = 0
        # original runbook or generated from test case which this environment supports
        self.runbook: schema.Environment
        self.warn_as_error = warn_as_error
        self._default_node: Optional[Node] = None
        self._log = get_logger("env", self.name)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if self.status != EnvironmentStatus.Deployed:
            raise LisaException("environment is not deployed, cannot be initialized")
        self.nodes.initialize()
        self.status = EnvironmentStatus.Connected

    @property
    def status(self) -> EnvironmentStatus:
        return self._status

    @status.setter
    def status(self, value: EnvironmentStatus) -> None:
        self._status = value

    @classmethod
    def create(
        cls, runbook: schema.Environment, is_predefined: bool, warn_as_error: bool
    ) -> Environment:
        environment = Environment(
            is_predefined=is_predefined, warn_as_error=warn_as_error
        )
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

    @property
    def capability(self) -> EnvironmentSpace:
        result = EnvironmentSpace(topology=self.runbook.topology)
        for node in self.nodes.list():
            result.nodes.append(node.capability)
        if (
            self.status in [EnvironmentStatus.Prepared, EnvironmentStatus.New]
            and self.runbook.nodes_requirement
        ):
            result.nodes.extend(self.runbook.nodes_requirement)
        return result

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

    def get_or_create(self, requirement: EnvironmentSpace) -> Optional[Environment]:
        result: Optional[Environment] = None
        for environment in self.values():
            # find exact match, or create a new one.
            if requirement == environment.capability:
                result = environment
                break
        else:
            result = self.from_requirement(requirement)
        return result

    def from_requirement(self, requirement: EnvironmentSpace) -> Optional[Environment]:
        runbook = schema.Environment(
            topology=requirement.topology,
            nodes_requirement=requirement.nodes,
        )
        return self.from_runbook(
            runbook=runbook,
            name=f"generated_{len(self.keys())}",
            is_original_runbook=False,
        )

    def from_runbook(
        self, runbook: schema.Environment, name: str, is_original_runbook: bool
    ) -> Optional[Environment]:
        assert runbook
        assert name
        env: Optional[Environment] = None
        if is_original_runbook or self.allow_create:
            # make a copy, so that modification on env won't impact test case
            copied_runbook = copy.copy(runbook)
            copied_runbook.name = name
            env = Environment.create(
                runbook=copied_runbook,
                is_predefined=is_original_runbook,
                warn_as_error=self.warn_as_error,
            )
            self[name] = env
            log = _get_init_logger()
            log.debug(f"created {env.name}: {env.runbook}")
        return env


def load_environments(
    root_runbook: Optional[schema.EnvironmentRoot],
) -> Environments:
    if root_runbook:
        environments = Environments(
            warn_as_error=root_runbook.warn_as_error,
            max_concurrency=root_runbook.max_concurrency,
            allow_create=root_runbook.allow_create,
        )

        environments_runbook = root_runbook.environments
        for environment_runbook in environments_runbook:
            env = environments.from_runbook(
                runbook=environment_runbook,
                name=f"customized_{len(environments)}",
                is_original_runbook=True,
            )
            assert env, "created from runbook shouldn't be None"
    else:
        environments = Environments()

    return environments
