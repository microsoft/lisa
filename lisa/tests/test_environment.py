from typing import Any, List
from unittest import TestCase

from lisa import schema, search_space
from lisa.environment import load_environments
from lisa.testsuite import simple_requirement
from lisa.util import constants


def generate_runbook(
    is_single_env: bool = False,
    local: bool = False,
    remote: bool = False,
    requirement: bool = False,
) -> schema.EnvironmentRoot:
    environments: List[Any] = list()
    nodes: List[Any] = list()
    if local:
        nodes.append(
            {
                constants.TYPE: constants.ENVIRONMENTS_NODES_LOCAL,
                constants.ENVIRONMENTS_NODES_CAPABILITY: {"coreCount": {"min": 4}},
            }
        )
    if remote:
        nodes.append(
            {
                constants.TYPE: constants.ENVIRONMENTS_NODES_REMOTE,
                constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS: "internal_address",
                constants.ENVIRONMENTS_NODES_REMOTE_PORT: 22,
                "publicAddress": "public_address",
                "publicPort": 10022,
                constants.ENVIRONMENTS_NODES_REMOTE_USERNAME: "name_of_user",
                constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD: "dont_use_it",
            }
        )
    if requirement:
        nodes.append(
            {
                constants.TYPE: constants.ENVIRONMENTS_NODES_REQUIREMENT,
                "nodeCount": 2,
                "coreCount": 8,
                "diskCount": {"min": 1},
                "nicCount": {"min": 1, "max": 1},
            }
        )
    if is_single_env:
        environments = [{"nodes": nodes}]
    else:
        for node in nodes:
            environments.append({"nodes": [node]})

    data = {"maxConcurrency": 2, constants.ENVIRONMENTS: environments}
    return schema.EnvironmentRoot.schema().load(data)  # type: ignore


class EnvironmentTestCase(TestCase):
    def test_load_empty_runbook(self) -> None:
        envs = load_environments(None)
        self.assertEqual(0, len(envs))
        self.assertEqual(False, envs.warn_as_error)
        self.assertEqual(1, envs.max_concurrency)
        self.assertEqual(True, envs.allow_create)

    def test_create_from_runbook_splited(self) -> None:
        runbook = generate_runbook(local=True, remote=True)
        envs = load_environments(runbook)
        self.assertEqual(2, len(envs))
        for env in envs.values():
            for node in env.nodes.list():
                # mock initializing
                node._is_initialized = True
            self.assertEqual(1, len(env.nodes))

    def test_create_from_runbook_merged(self) -> None:
        runbook = generate_runbook(is_single_env=True, local=True, remote=True)
        envs = load_environments(runbook)
        self.assertEqual(1, len(envs))
        for env in envs.values():
            for node in env.nodes.list():
                # mock initializing
                node._is_initialized = True
            self.assertEqual(2, len(env.nodes))

    def test_create_from_runbook_cap(self) -> None:
        runbook = generate_runbook(local=True, requirement=True)
        envs = load_environments(runbook)
        self.assertEqual(2, len(envs))
        env = envs.get("customized_0")
        assert env
        for node in env.nodes.list():
            # mock initializing
            node._is_initialized = True
        self.assertEqual(search_space.IntRange(min=4), node.capability.core_count)
        self.assertEqual(search_space.IntRange(min=1), node.capability.disk_count)
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
        self.assertIsNone(env.runbook.nodes)
        assert env.runbook.nodes_requirement
        self.assertEqual(2, len(env.runbook.nodes_requirement))
