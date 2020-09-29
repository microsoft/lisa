from typing import List, Type
from unittest.case import TestCase

from lisa import schema
from lisa.environment import Environment, Environments, load_environments
from lisa.feature import Feature
from lisa.platform_ import Platform, WaitMoreResourceError, load_platform
from lisa.tests.test_environment import generate_runbook as generate_env_runbook
from lisa.util import LisaException, constants
from lisa.util.logger import Logger

# for other UT to set value
return_prepared = True
deploy_success = True
deploy_is_ready = True
wait_more_resource_error = False
prepared_envs: List[str] = []
deployed_envs: List[str] = []
deleted_envs: List[str] = []


class MockPlatform(Platform):
    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)
        prepared_envs.clear()
        deployed_envs.clear()
        deleted_envs.clear()
        self.set_test_config(
            return_prepared=return_prepared,
            deploy_success=deploy_success,
            deploy_is_ready=deploy_is_ready,
            wait_more_resource_error=wait_more_resource_error,
        )

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
        deploy_is_ready: bool = True,
        wait_more_resource_error: bool = False,
    ) -> None:
        self.return_prepared = return_prepared
        self.deploy_success = deploy_success
        self.deploy_is_ready = deploy_is_ready
        self.wait_more_resource_error = wait_more_resource_error

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        prepared_envs.append(environment.name)
        requirements = environment.runbook.nodes_requirement
        if self.return_prepared and requirements:
            min_capabilities: List[schema.NodeSpace] = []
            for node_space in requirements:
                min_capabilities.append(node_space.generate_min_capability(node_space))
            environment.runbook.nodes_requirement = min_capabilities
        return self.return_prepared

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        if self.wait_more_resource_error:
            raise WaitMoreResourceError("wait more resource")
        if not self.deploy_success:
            raise LisaException("mock deploy failed")
        if self.return_prepared and environment.runbook.nodes_requirement:
            requirements = environment.runbook.nodes_requirement
            for node_space in requirements:
                environment.nodes.from_requirement(node_requirement=node_space)
        deployed_envs.append(environment.name)
        environment._is_initialized = True
        environment.is_ready = self.deploy_is_ready

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        deleted_envs.append(environment.name)
        self.delete_called = True


def generate_platform(
    reserve_environment: bool = False,
    admin_password: str = "donot use for real",
    admin_key_file: str = "",
) -> MockPlatform:
    runbook_data = {
        constants.TYPE: constants.PLATFORM_MOCK,
        "reserveEnvironment": reserve_environment,
        "adminPassword": admin_password,
        "adminPrivateKeyFile": admin_key_file,
    }
    runbook = schema.Platform.schema().load(runbook_data)  # type: ignore
    platform = load_platform([runbook])
    try:
        assert isinstance(platform, MockPlatform), f"actual: {type(platform)}"
    except AssertionError:
        # as UT imported from tests package, instaed of from lisa.tests package
        # ignore by assign type from current package
        platform = MockPlatform(runbook)
    return platform


def generate_environments() -> Environments:
    envs_runbook = generate_env_runbook(local=True, requirement=True)
    envs = load_environments(envs_runbook)

    return envs


class PlatformTestCase(TestCase):
    def test_prepared_env_not_success_dropped(self) -> None:
        platform = generate_platform()
        platform.set_test_config(return_prepared=False)
        envs = generate_environments()
        self.assertEqual(2, len(envs))
        prepared_environments = platform.prepare_environments(envs)
        self.assertEqual(0, len(prepared_environments))

    def test_prepared_env_success(self) -> None:
        platform = generate_platform()
        platform.set_test_config(return_prepared=True)
        envs = generate_environments()
        self.assertEqual(2, len(envs))
        prepared_environments = platform.prepare_environments(envs)
        self.assertEqual(2, len(prepared_environments))

    def test_prepared_env_sorted_predefined_first(self) -> None:
        platform = generate_platform()
        platform.set_test_config()
        envs = generate_environments()

        # verify init as expected
        self.assertListEqual(["runbook_0", "runbook_1"], [x for x in envs])
        self.assertListEqual([True, True], [x.is_predefined for x in envs.values()])

        # verify stable sort
        envs["runbook_1"].is_predefined = False
        prepared_environments = platform.prepare_environments(envs)
        self.assertListEqual(
            ["runbook_0", "runbook_1"], [x.name for x in prepared_environments]
        )
        self.assertListEqual(
            [True, False], [x.is_predefined for x in prepared_environments]
        )

        # verify reverse sort
        envs["runbook_0"].is_predefined = False
        envs["runbook_1"].is_predefined = True
        prepared_environments = platform.prepare_environments(envs)
        self.assertListEqual(
            ["runbook_1", "runbook_0"],
            [x.name for x in prepared_environments],
        )
        self.assertListEqual(
            [True, False], [x.is_predefined for x in prepared_environments]
        )

    def test_prepared_env_sorted_by_cost(self) -> None:
        platform = generate_platform()
        envs = generate_environments()
        platform.set_test_config()

        self.assertListEqual(["runbook_0", "runbook_1"], [x for x in envs])
        self.assertListEqual([0, 0], [x.cost for x in envs.values()])

        envs["runbook_0"].cost = 1
        envs["runbook_1"].cost = 2
        prepared_environments = platform.prepare_environments(envs)
        self.assertListEqual(
            ["runbook_0", "runbook_1"], [x.name for x in prepared_environments]
        )
        self.assertListEqual([1, 2], [x.cost for x in prepared_environments])

        envs["runbook_0"].cost = 2
        envs["runbook_1"].cost = 1
        prepared_environments = platform.prepare_environments(envs)
        self.assertListEqual(
            ["runbook_1", "runbook_0"], [x.name for x in prepared_environments]
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
            self.assertEqual(True, env.is_ready)
            platform.delete_environment(env)
            self.assertEqual(False, env.is_ready)
