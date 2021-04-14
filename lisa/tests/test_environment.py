# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Type, cast
from unittest import TestCase

from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import node, schema, search_space
from lisa.environment import load_environments
from lisa.testsuite import simple_requirement
from lisa.util import constants

CUSTOM_LOCAL = "custom_local"
CUSTOM_REMOTE = "custom_remote"


@dataclass_json()
@dataclass
class CustomLocalNodeSchema(schema.LocalNode):
    type: str = field(
        default=CUSTOM_LOCAL,
        metadata=schema.metadata(
            required=True,
            validate=validate.OneOf([CUSTOM_LOCAL]),
        ),
    )

    custom_local_field: Optional[str] = field(default=None)


class CustomLocalNode(node.LocalNode):
    def __init__(
        self,
        index: int,
        runbook: CustomLocalNodeSchema,
        logger_name: str,
        base_log_path: Optional[Path] = None,
    ) -> None:
        super().__init__(
            index=index,
            runbook=runbook,
            logger_name=logger_name,
            base_log_path=base_log_path,
        )
        self.custom_local_field = runbook.custom_local_field
        assert (
            self.custom_local_field
        ), f"custom_local_field field of {CUSTOM_LOCAL}-typed nodes cannot be empty"

    @classmethod
    def type_name(cls) -> str:
        return CUSTOM_LOCAL

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return CustomLocalNodeSchema


@dataclass_json()
@dataclass
class CustomRemoteNodeSchema(schema.RemoteNode):
    type: str = field(
        default=CUSTOM_REMOTE,
        metadata=schema.metadata(
            required=True,
            validate=validate.OneOf([CUSTOM_REMOTE]),
        ),
    )

    custom_remote_field: Optional[str] = field(default=None)


class CustomRemoteNode(node.RemoteNode):
    def __init__(
        self,
        index: int,
        runbook: CustomRemoteNodeSchema,
        logger_name: str,
        base_log_path: Optional[Path] = None,
    ) -> None:
        super().__init__(
            index=index,
            runbook=runbook,
            logger_name=logger_name,
            base_log_path=base_log_path,
        )
        self.custom_remote_field = runbook.custom_remote_field
        assert (
            self.custom_remote_field
        ), f"custom_remote_field field of {CUSTOM_REMOTE}-typed nodes cannot be empty"

    @classmethod
    def type_name(cls) -> str:
        return CUSTOM_REMOTE

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return CustomRemoteNodeSchema


def generate_runbook(
    is_single_env: bool = False,
    local: bool = False,
    remote: bool = False,
    requirement: bool = False,
    local_remote_node_extensions: bool = False,
) -> schema.EnvironmentRoot:
    environments: List[Any] = list()
    nodes: List[Any] = list()
    if local:
        nodes.append(
            {
                constants.TYPE: constants.ENVIRONMENTS_NODES_LOCAL,
                constants.ENVIRONMENTS_NODES_CAPABILITY: {"core_count": {"min": 4}},
            }
        )
    if remote:
        nodes.append(
            {
                constants.TYPE: constants.ENVIRONMENTS_NODES_REMOTE,
                constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS: "internal_address",
                constants.ENVIRONMENTS_NODES_REMOTE_PORT: 22,
                "public_address": "public_address",
                "public_port": 10022,
                constants.ENVIRONMENTS_NODES_REMOTE_USERNAME: "name_of_user",
                constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD: "do_not_use_it",
            }
        )
    if requirement:
        nodes.append(
            {
                constants.TYPE: constants.ENVIRONMENTS_NODES_REQUIREMENT,
                "node_count": 2,
                "core_count": 8,
                "disk_count": {"min": 1},
                "nic_count": {"min": 1, "max": 1},
            }
        )
    if local_remote_node_extensions:
        nodes.extend(
            [
                {
                    constants.TYPE: CUSTOM_LOCAL,
                    constants.ENVIRONMENTS_NODES_CAPABILITY: {"core_count": {"min": 4}},
                    "custom_local_field": CUSTOM_LOCAL,
                },
                {
                    constants.TYPE: CUSTOM_REMOTE,
                    constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS: "internal_address",
                    constants.ENVIRONMENTS_NODES_REMOTE_PORT: 22,
                    "public_address": "public_address",
                    "public_port": 10022,
                    constants.ENVIRONMENTS_NODES_REMOTE_USERNAME: "name_of_user",
                    constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD: "do_not_use_it",
                    "custom_remote_field": CUSTOM_REMOTE,
                },
            ]
        )
    if is_single_env:
        environments = [{"nodes": nodes}]
    else:
        for n in nodes:
            environments.append({"nodes": [n]})

    data = {"max_concurrency": 2, constants.ENVIRONMENTS: environments}
    return schema.EnvironmentRoot.schema().load(data)  # type: ignore


class EnvironmentTestCase(TestCase):
    def test_load_empty_runbook(self) -> None:
        envs = load_environments(None)
        self.assertEqual(0, len(envs))
        self.assertEqual(False, envs.warn_as_error)
        self.assertEqual(1, envs.max_concurrency)
        self.assertEqual(True, envs.allow_create)

    def test_create_from_runbook_split(self) -> None:
        runbook = generate_runbook(local=True, remote=True)
        envs = load_environments(runbook)
        self.assertEqual(2, len(envs))
        for env in envs.values():
            for n in env.nodes.list():
                # mock initializing
                n._is_initialized = True
            self.assertEqual(1, len(env.nodes))

    def test_create_from_runbook_merged(self) -> None:
        runbook = generate_runbook(is_single_env=True, local=True, remote=True)
        envs = load_environments(runbook)
        self.assertEqual(1, len(envs))
        for env in envs.values():
            for n in env.nodes.list():
                # mock initializing
                n._is_initialized = True
            self.assertEqual(2, len(env.nodes))

    def test_create_from_runbook_cap(self) -> None:
        runbook = generate_runbook(local=True, requirement=True)
        envs = load_environments(runbook)
        self.assertEqual(2, len(envs))
        env = envs.get("customized_0")
        assert env
        for n in env.nodes.list():
            # mock initializing
            n._is_initialized = True
        self.assertEqual(search_space.IntRange(min=4), n.capability.core_count)
        self.assertEqual(search_space.IntRange(min=1), n.capability.disk_count)
        # check from env capability
        env_cap = env.capability
        self.assertEqual(1, len(env_cap.nodes))
        self.assertEqual(search_space.IntRange(min=4), env_cap.nodes[0].core_count)
        self.assertEqual(search_space.IntRange(min=1), env_cap.nodes[0].disk_count)

        # test pure node_requirement
        env = envs.get("customized_1")
        assert env
        env_cap = env.capability
        self.assertEqual(2, len(env_cap.nodes))
        self.assertEqual(8, env_cap.nodes[0].core_count)
        self.assertEqual(search_space.IntRange(min=1), env_cap.nodes[0].disk_count)
        self.assertEqual(
            search_space.IntRange(min=1, max=1), env_cap.nodes[0].nic_count
        )

    def test_create_from_requirement(self) -> None:
        requirement = simple_requirement(min_count=2)
        env_requirement = requirement.environment
        assert env_requirement
        envs = load_environments(None)
        env = envs.get_or_create(requirement=env_requirement)
        assert env
        self.assertEqual(1, len(envs))

        requirement = simple_requirement(min_count=2)
        env_requirement = requirement.environment
        assert env_requirement
        env = envs.get_or_create(requirement=env_requirement)
        self.assertEqual(1, len(envs), "get or create again won't create new")
        assert env
        self.assertEqual(0, len(env.nodes))
        self.assertSequenceEqual([], env.runbook.nodes)
        assert env.runbook.nodes_requirement
        self.assertEqual(2, len(env.runbook.nodes_requirement))

    def test_create_from_custom_local_remote(self) -> None:
        runbook = generate_runbook(
            local_remote_node_extensions=True, is_single_env=True
        )
        envs = load_environments(runbook)
        self.assertEqual(1, len(envs))
        for env in envs.values():
            done: int = 0
            for n in env.nodes.list():
                if n.type_name() == CUSTOM_LOCAL:
                    l_n = cast(CustomLocalNode, n)
                    self.assertEqual(l_n.custom_local_field, CUSTOM_LOCAL)
                    done += 1
                elif n.type_name() == CUSTOM_REMOTE:
                    r_n = cast(CustomRemoteNode, n)
                    self.assertEqual(r_n.custom_remote_field, CUSTOM_REMOTE)
                    done += 1
            self.assertEqual(2, done)
