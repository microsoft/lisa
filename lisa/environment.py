# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import copy
from collections import UserDict
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import notifier, schema, search_space
from lisa.node import Node, Nodes
from lisa.notifier import MessageBase
from lisa.util import (
    ContextMixin,
    InitializableMixin,
    LisaException,
    constants,
    field_metadata,
    get_datetime_path,
    hookimpl,
    hookspec,
    is_unittest,
    plugin_manager,
)
from lisa.util.logger import create_file_handler, get_logger, remove_handler

if TYPE_CHECKING:
    from lisa.platform_ import Platform
    from lisa.testsuite import TestResult


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
        # initialized and connected via SSH
        "Connected",
        # deleted by platform
        "Deleted",
        # the environment is in a bad state, and need to be deleted.
        "Bad",
    ],
)

_global_environment_id = 0
_global_environment_id_lock: Lock = Lock()


def _get_environment_id() -> int:
    """
    Return an unique id crossing threads, runners.
    """
    global _global_environment_id

    with _global_environment_id_lock:
        env_id = _global_environment_id
        _global_environment_id += 1

    return env_id


@dataclass
class EnvironmentMessage(MessageBase):
    type: str = "Environment"
    name: str = ""
    runbook: schema.Environment = schema.Environment()
    status: EnvironmentStatus = EnvironmentStatus.New
    log_folder: Path = Path()


@dataclass_json()
@dataclass
class EnvironmentSpace(search_space.RequirementMixin):
    """
    Search space of an environment. It uses to
    1. Specify test suite requirement, see TestCaseRequirement
    2. Describe capability of an environment, see Environment.capability
    """

    topology: str = field(
        default=constants.ENVIRONMENTS_SUBNET,
        metadata=field_metadata(
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
                f"requirement: {len(self.nodes)}, "
                f"capability: {len(capability.nodes)}."
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
    def __init__(
        self,
        is_predefined: bool,
        warn_as_error: bool,
        id_: int,
        runbook: schema.Environment,
    ) -> None:
        super().__init__()

        self.nodes: Nodes
        self.runbook = runbook
        self.name = runbook.name
        self.is_predefined: bool = is_predefined
        self.is_new: bool = True
        self.id: str = str(id_)
        self.warn_as_error = warn_as_error
        self.platform: Optional[Platform] = None
        self.log = get_logger("env", self.name)
        self.source_test_result: Optional[TestResult] = None

        self._default_node: Optional[Node] = None
        self._is_dirty: bool = False

        # track retried times to provide an unique name.
        self._raw_id = id_
        self._retries: int = 0

        # cost uses to plan order of environments.
        # cheaper env can fit cases earlier to run more cases on it.
        # 1. smaller is higher priority, it can be index of candidate environment
        # 2. 0 means no cost.
        self.cost: float = 0

        # indicate is this environment is deploying, preparing, testing or not.
        self.is_in_use: bool = False

        # Not to set the log path until its first used. Because the path
        # contains environment name, which is not set in __init__.
        self._log_path: Optional[Path] = None
        self._working_path: Optional[Path] = None
        # it's used to compose a consistent path for both log and working path.
        self.environment_part_path = Path(
            f"environments/{get_datetime_path()}-{self.name}"
        )

        self._status: Optional[EnvironmentStatus] = None
        self.status = EnvironmentStatus.New

    def __repr__(self) -> str:
        return self.name

    @property
    def status(self) -> EnvironmentStatus:
        assert self._status
        return self._status

    @status.setter
    def status(self, value: EnvironmentStatus) -> None:
        # sometimes there are duplicated messages, ignore if no change.
        if self._status != value:
            if value == EnvironmentStatus.New:
                self._reset()
            self._status = value
            environment_message = EnvironmentMessage(
                name=self.name,
                status=self._status,
                runbook=self.runbook,
                log_folder=self.environment_part_path,
            )
            notifier.notify(environment_message)

    @property
    def is_alive(self) -> bool:
        return self._status in [
            EnvironmentStatus.New,
            EnvironmentStatus.Prepared,
            EnvironmentStatus.Deployed,
            EnvironmentStatus.Connected,
        ]

    @property
    def default_node(self) -> Node:
        return self.nodes.default

    @property
    def log_path(self) -> Path:
        # avoid to create path for UT. There may be path conflict in UT.
        if is_unittest():
            return Path()

        if not self._log_path:
            self._log_path = constants.RUN_LOCAL_LOG_PATH / self.environment_part_path
            self._log_path.mkdir(parents=True, exist_ok=True)

        return self._log_path

    @property
    def working_path(self) -> Path:
        if is_unittest():
            return Path()

        if not self._working_path:
            self._working_path = (
                constants.RUN_LOCAL_WORKING_PATH / self.environment_part_path
            )
            self._working_path.mkdir(parents=True, exist_ok=True)

        return self._working_path

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

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty or any(x.is_dirty for x in self.nodes.list())

    def cleanup(self) -> None:
        self.nodes.cleanup()
        if hasattr(self, "_log_handler") and self._log_handler:
            remove_handler(self._log_handler, self.log)
            self._log_handler.close()

    def close(self) -> None:
        self.nodes.close()

    def create_node_from_exists(
        self,
        node_runbook: schema.Node,
    ) -> Node:
        node = Node.create(
            index=len(self.nodes),
            runbook=node_runbook,
            base_part_path=self.environment_part_path,
            parent_logger=self.log,
        )
        self.nodes.append(node)

        return node

    def create_node_from_requirement(
        self,
        node_requirement: schema.NodeSpace,
    ) -> Node:
        min_requirement = cast(
            schema.Capability,
            node_requirement.generate_min_capability(node_requirement),
        )
        assert isinstance(min_requirement.node_count, int), (
            f"must be int after generate_min_capability, "
            f"actual: {min_requirement.node_count}"
        )
        # node count should be expanded in platform already
        assert min_requirement.node_count == 1, f"actual: {min_requirement.node_count}"
        mock_runbook = schema.RemoteNode(
            type=constants.ENVIRONMENTS_NODES_REMOTE,
            capability=min_requirement,
            is_default=node_requirement.is_default,
        )
        node = Node.create(
            index=len(self.nodes),
            runbook=mock_runbook,
            base_part_path=self.environment_part_path,
            parent_logger=self.log,
        )
        self.nodes.append(node)

        return node

    def get_information(self) -> Dict[str, str]:
        final_information: Dict[str, str] = {}
        informations: List[
            Dict[str, str]
        ] = plugin_manager.hook.get_environment_information(environment=self)
        # reverse it, since it's FILO order,
        # try basic earlier, and they are allowed to be overwritten
        informations.reverse()
        for current_information in informations:
            final_information.update(current_information)

        return final_information

    def mark_dirty(self) -> None:
        self.log.debug("mark environment to dirty")
        self._is_dirty = True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if self.status != EnvironmentStatus.Deployed:
            raise LisaException("environment is not deployed, cannot be initialized")
        if not hasattr(self, "_log_handler"):
            self._log_handler = create_file_handler(
                self.log_path / "environment.log", self.log
            )
        self.nodes.initialize()
        self.status = EnvironmentStatus.Connected

    def _reset(self) -> None:
        self.nodes = Nodes()
        self.runbook.reload_requirements()

        self.is_new = True

        if not self.runbook.nodes_requirement and not self.runbook.nodes:
            raise LisaException("not found any node or requirement in environment")

        has_default_node = False
        for node_runbook in self.runbook.nodes:
            self.create_node_from_exists(
                node_runbook=node_runbook,
            )

            has_default_node = self._validate_single_default(
                has_default_node, node_runbook.is_default
            )

        if self._retries > 0:
            # provide an unique id.
            self.id = f"{self._raw_id}-{self._retries}"

        self.remove_context()

        self._retries += 1

    def _validate_single_default(
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
    ) -> None:
        super().__init__()
        self.warn_as_error = warn_as_error

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
        id_ = _get_environment_id()
        return self.from_runbook(
            runbook=runbook,
            name=f"generated_{id_}",
            is_predefined_runbook=False,
            id_=id_,
        )

    def from_runbook(
        self,
        runbook: schema.Environment,
        name: str,
        is_predefined_runbook: bool,
        id_: int,
    ) -> Optional[Environment]:
        assert runbook
        assert name
        env: Optional[Environment] = None

        # make a copy, so that modification on env won't impact test case
        copied_runbook = copy.copy(runbook)
        copied_runbook.name = name
        env = Environment(
            is_predefined=is_predefined_runbook,
            warn_as_error=self.warn_as_error,
            id_=id_,
            runbook=copied_runbook,
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
        )

        environments_runbook = root_runbook.environments
        for environment_runbook in environments_runbook:
            id_ = _get_environment_id()
            env = environments.from_runbook(
                runbook=environment_runbook,
                name=environment_runbook.name or f"customized_{id_}",
                is_predefined_runbook=True,
                id_=id_,
            )
            assert env, "created from runbook shouldn't be None"
    else:
        environments = Environments()

    return environments


class EnvironmentHookSpec:
    @hookspec
    def get_environment_information(self, environment: Environment) -> Dict[str, str]:
        ...


class EnvironmentHookImpl:
    @hookimpl
    def get_environment_information(self, environment: Environment) -> Dict[str, str]:
        information: Dict[str, str] = {}
        information["name"] = environment.name

        if environment.nodes:
            node = environment.default_node
            try:
                information = node.get_information()
            except Exception as identifier:
                environment.log.exception(
                    "failed to get environment information", exc_info=identifier
                )

        return information


plugin_manager.add_hookspecs(EnvironmentHookSpec)
plugin_manager.register(EnvironmentHookImpl())
