# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, List, Optional, Type, Union
from unittest.case import TestCase

from dataclasses_json import dataclass_json

import lisa
from lisa import schema
from lisa.environment import (
    Environment,
    Environments,
    EnvironmentStatus,
    LisaException,
    constants,
    load_environments,
)
from lisa.feature import Feature
from lisa.platform_ import Platform, load_platform
from lisa.util import ResourceAwaitableException, plugin_manager
from lisa.util.logger import Logger
from selftests.test_environment import generate_runbook as generate_env_runbook


@dataclass
class MockPlatformTestData:
    prepared_envs: List[str] = field(default_factory=list)
    deployed_envs: List[str] = field(default_factory=list)
    deleted_envs: List[str] = field(default_factory=list)


@dataclass_json()
@dataclass
class MockPlatformSchema:
    # for other UT to set value
    return_prepared: bool = True
    deploy_success: bool = True
    deployed_status: EnvironmentStatus = EnvironmentStatus.Deployed
    wait_more_resource_error: bool = False


class MockPlatform(Platform):
    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)
        self.test_data = MockPlatformTestData()
        # prevent real calls
        for plugin_name, _ in plugin_manager.list_name_plugin():
            plugin_manager.unregister(name=plugin_name)

    @classmethod
    def type_name(cls) -> str:
        return constants.PLATFORM_MOCK

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return []

    def set_test_config(
        self,
        return_prepared: bool = True,
        deploy_success: bool = True,
        deployed_status: EnvironmentStatus = EnvironmentStatus.Deployed,
        wait_more_resource_error: bool = False,
    ) -> None:
        self.initialize()
        self._mock_runbook.return_prepared = return_prepared
        self._mock_runbook.deploy_success = deploy_success
        self._mock_runbook.deployed_status = deployed_status
        self._mock_runbook.wait_more_resource_error = wait_more_resource_error

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._mock_runbook: MockPlatformSchema = self.runbook.get_extended_runbook(
            MockPlatformSchema, constants.PLATFORM_MOCK
        )

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        self.test_data.prepared_envs.append(environment.name)
        requirements = environment.runbook.nodes_requirement
        if self._mock_runbook.return_prepared and requirements:
            min_capabilities: List[schema.NodeSpace] = []
            for node_space in requirements:
                min_capabilities.append(node_space.generate_min_capability(node_space))
            environment.runbook.nodes_requirement = min_capabilities
        return self._mock_runbook.return_prepared

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        if self._mock_runbook.wait_more_resource_error:
            raise ResourceAwaitableException("any", "wait more resource")
        if not self._mock_runbook.deploy_success:
            raise LisaException("mock deploy failed")
        if self._mock_runbook.return_prepared and environment.runbook.nodes_requirement:
            requirements = environment.runbook.nodes_requirement
            for node_space in requirements:
                environment.create_node_from_requirement(node_requirement=node_space)
        for node in environment.nodes.list():
            node._is_initialized = True
        self.test_data.deployed_envs.append(environment.name)
        if self._mock_runbook.deployed_status not in [
            EnvironmentStatus.Deployed,
            EnvironmentStatus.Connected,
        ]:
            raise LisaException(
                f"expected status is {self._mock_runbook.deployed_status}, "
                f"deployment should be failed"
            )

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        self.test_data.deleted_envs.append(environment.name)
        self.delete_called = True


def generate_platform(
    keep_environment: Optional[Union[str, bool]] = False,
    admin_password: str = "do not use for real",
    admin_key_file: str = "",
) -> MockPlatform:
    runbook_data = {
        constants.TYPE: constants.PLATFORM_MOCK,
        "keep_environment": keep_environment,
        "admin_password": admin_password,
        "admin_private_key_file": admin_key_file,
    }
    runbook = schema.load_by_type(schema.Platform, runbook_data)
    platform = load_platform([runbook])
    platform.initialize()
    try:
        assert isinstance(platform, MockPlatform), f"actual: {type(platform)}"
    except AssertionError:
        # as UT imported from tests package, instead of from lisa.tests package
        # ignore by assign type from current package
        platform = MockPlatform(runbook)
    return platform


def generate_environments() -> Environments:
    envs_runbook = generate_env_runbook(local=True, requirement=True)
    envs = load_environments(envs_runbook)

    return envs


class PlatformTestCase(TestCase):
    def setUp(self) -> None:
        lisa.environment._global_environment_id = 0

    def test_prepared_env_not_success_with_exception(self) -> None:
        platform = generate_platform()
        platform.set_test_config(return_prepared=False)
        envs = generate_environments()
        self.assertEqual(2, len(envs))
        with self.assertRaises(LisaException) as cm:
            [platform.prepare_environment(env) for env in envs.values()]
        self.assertEqual(
            "no capability found for environment: Environment("
            "name='customized_0', topology='subnet', nodes_raw=[{'type': 'local', "
            "'capability': {'core_count': {'min': 4}}}], nodes_requirement=None, "
            "enabled=True, _original_nodes_requirement=None)",
            str(cm.exception),
        )

    def test_prepared_env_success(self) -> None:
        platform = generate_platform()
        platform.set_test_config(return_prepared=True)
        envs = generate_environments()
        self.assertEqual(2, len(envs))
        prepared_environments = [
            platform.prepare_environment(env) for env in envs.values()
        ]
        self.assertEqual(2, len(prepared_environments))

    def test_prepared_env_sorted_predefined_first(self) -> None:
        platform = generate_platform()
        platform.set_test_config()
        envs = generate_environments()

        # verify init as expected
        self.assertListEqual(["customized_0", "customized_1"], [x for x in envs])
        self.assertListEqual([True, True], [x.is_predefined for x in envs.values()])

        # verify stable sort
        envs["customized_1"].is_predefined = False
        prepared_environments = [
            platform.prepare_environment(env) for env in envs.values()
        ]
        prepared_environments.sort(key=lambda x: (not x.is_predefined, x.cost))
        self.assertListEqual(
            ["customized_0", "customized_1"], [x.name for x in prepared_environments]
        )
        self.assertListEqual(
            [True, False], [x.is_predefined for x in prepared_environments]
        )

        # verify reverse sort
        envs["customized_0"].is_predefined = False
        envs["customized_1"].is_predefined = True
        prepared_environments = [
            platform.prepare_environment(env) for env in envs.values()
        ]
        prepared_environments.sort(key=lambda x: (not x.is_predefined, x.cost))
        self.assertListEqual(
            ["customized_1", "customized_0"],
            [x.name for x in prepared_environments],
        )
        self.assertListEqual(
            [True, False], [x.is_predefined for x in prepared_environments]
        )

    def test_prepared_env_sorted_by_cost(self) -> None:
        platform = generate_platform()
        envs = generate_environments()
        platform.set_test_config()

        self.assertListEqual(["customized_0", "customized_1"], [x for x in envs])
        self.assertListEqual([0, 0], [x.cost for x in envs.values()])

        envs["customized_0"].cost = 1
        envs["customized_1"].cost = 2
        prepared_environments = [
            platform.prepare_environment(env) for env in envs.values()
        ]
        prepared_environments.sort(key=lambda x: (not x.is_predefined, x.cost))
        self.assertListEqual(
            ["customized_0", "customized_1"], [x.name for x in prepared_environments]
        )
        self.assertListEqual([1, 2], [x.cost for x in prepared_environments])

        envs["customized_0"].cost = 2
        envs["customized_1"].cost = 1
        prepared_environments = [
            platform.prepare_environment(env) for env in envs.values()
        ]
        prepared_environments.sort(key=lambda x: (not x.is_predefined, x.cost))
        self.assertListEqual(
            ["customized_1", "customized_0"], [x.name for x in prepared_environments]
        )
        self.assertListEqual([1, 2], [x.cost for x in prepared_environments])

    def test_prepared_env_deploy_failed(self) -> None:
        platform = generate_platform()
        envs = generate_environments()
        platform.set_test_config(deploy_success=False)
        for env in envs.values():
            with self.assertRaises(LisaException) as cm:
                platform.deploy_environment(env)
            self.assertEqual("mock deploy failed", str(cm.exception))

    def test_prepared_env_deleted_not_ready(self) -> None:
        platform = generate_platform()
        envs = generate_environments()
        platform.set_test_config()
        for env in envs.values():
            platform.deploy_environment(env)
            self.assertEqual(EnvironmentStatus.Deployed, env.status)
            platform.delete_environment(env)
            self.assertEqual(EnvironmentStatus.Deleted, env.status)
