from typing import List, Optional, cast
from unittest import IsolatedAsyncioTestCase

from lisa import schema
from lisa.environment import EnvironmentStatus, load_environments
from lisa.runner import Runner
from lisa.tests import test_platform, test_testsuite
from lisa.tests.test_environment import generate_runbook as generate_env_runbook
from lisa.tests.test_testsuite import (
    cleanup_cases_metadata,
    generate_cases_metadata,
    generate_cases_result,
)
from lisa.testsuite import TestResult, TestStatus, simple_requirement
from lisa.util import constants


def generate_runner(
    env_runbook: Optional[schema.EnvironmentRoot] = None,
    case_use_new_env: bool = False,
    platform_schema: Optional[test_platform.MockPlatformSchema] = None,
) -> Runner:
    platform_runbook = schema.Platform(
        type=constants.PLATFORM_MOCK, admin_password="do-not-use"
    )
    if platform_schema:
        platform_runbook.extended_schemas = {
            constants.PLATFORM_MOCK: platform_schema.to_dict()  # type:ignore
        }
    runbook = schema.Runbook(
        platform=[platform_runbook],
        testcase=[
            schema.TestCase(
                criteria=schema.Criteria(priority=[0, 1, 2]),
                use_new_environment=case_use_new_env,
            )
        ],
    )
    if env_runbook:
        runbook.environment = env_runbook
    runner = Runner(runbook)

    return runner


class RunnerTestCase(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        cleanup_cases_metadata()  # Necessary side effects!

    def test_merge_req_create_on_new(self) -> None:
        # if no predefined envs, can generate from requirement
        env_runbook = generate_env_runbook(is_single_env=False)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [],
            [x for x in envs],
        )
        runner = generate_runner(None)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # 3 cases create 3 environments.
        self.assertListEqual(
            ["generated_0", "generated_1", "generated_2"],
            list(envs),
        )
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            expected_message=["", "", ""],
            test_results=test_results,
        )

    def test_merge_req_run_not_create_on_equal(self) -> None:
        # when merging requirement from test cases,
        # it won't create new, if predefined exact match test case needs
        env_runbook = generate_env_runbook(remote=True)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            ["customized_0"],
            list(envs),
        )

        runner = generate_runner(env_runbook)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # 3 cases created only two required environments, as the
        # simple requirement was met by runbook_0.
        self.assertListEqual(
            ["customized_0", "generated_1", "generated_2"],
            list(envs),
        )
        self.assertListEqual(
            [TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            [x.status for x in test_results],
        )

    def test_merge_req_create_on_use_new(self) -> None:
        # same runbook as test_merge_req_run_not_create_on_equal
        # but all 3 cases asks a new env, so create 3 envs
        # note, when running cases, predefined env will be treat as a new env.
        env_runbook = generate_env_runbook(remote=True)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            ["customized_0"],
            list(envs),
        )
        runner = generate_runner(env_runbook)
        test_results = generate_cases_result()
        for test_result in test_results:
            test_result.runtime_data.use_new_environment = True
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # All 3 cases needed a new environment, so it created 3.
        self.assertListEqual(
            ["customized_0", "generated_1", "generated_2", "generated_3"],
            list(envs),
        )
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            expected_message=["", "", ""],
            test_results=test_results,
        )

    def test_merge_req_not_allow_create(self) -> None:
        # force to use existing env, not to create new.
        # this case doesn't provide predefined env, but no case skipped on this stage.
        env_runbook = generate_env_runbook(is_single_env=False)
        env_runbook.allow_create = False
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [],
            list(envs),
        )
        runner = generate_runner(None)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertListEqual(
            [],
            list(envs),
        )

        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.NOTRUN,
                TestStatus.NOTRUN,
                TestStatus.NOTRUN,
            ],
            expected_message=["", "", ""],
            test_results=test_results,
        )

    def test_merge_req_platform_type_checked(self) -> None:
        # check if current platform supported,
        # for example, some case run on azure only.
        # platform check happens in runner, so this case is here
        # a simple check is enough. More covered by search_space.SetSpace
        env_runbook = generate_env_runbook(is_single_env=False)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [],
            list(envs),
        )
        runner = generate_runner(None)
        test_results = generate_cases_result()
        for test_result in test_results:
            metadata = test_result.runtime_data.metadata
            metadata.requirement = simple_requirement(
                supported_platform_type=["does-not-exist"]
            )
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        platform_unsupported = "capability cannot support some of requirement"
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
            ],
            expected_message=[
                platform_unsupported,
                platform_unsupported,
                platform_unsupported,
            ],
            test_results=test_results,
        )

    async def test_fit_a_predefined_env(self) -> None:
        # predefined env can run case in below condition.
        # 1. with predefined env of 1 simple node, so ut2 don't need a new env
        # 2. ut3 need 8 cores, and predefined env target to meet all core requirement,
        #    so it can run any case with core requirements.
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, remote=True)
        runner = generate_runner(env_runbook)
        await runner.start()
        self.verify_env_results(
            expected_prepared=["customized_0", "generated_1", "generated_2"],
            expected_deployed_envs=["customized_0", "generated_1"],
            expected_deleted_envs=["customized_0", "generated_1"],
            runner=runner,
        )
        self.verify_test_results(
            expected_envs=["generated_1", "customized_0", "customized_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=runner._latest_test_results,
        )

    async def test_fit_a_bigger_env(self) -> None:
        # similar with test_fit_a_predefined_env, but predefined 2 nodes,
        # it doesn't equal to any case req, but reusable for all cases.

        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook)
        await runner.start()
        self.verify_env_results(
            expected_prepared=[
                "customized_0",
                "generated_1",
                "generated_2",
                "generated_3",
            ],
            expected_deployed_envs=["customized_0"],
            expected_deleted_envs=["customized_0"],
            runner=runner,
        )
        self.verify_test_results(
            expected_envs=["customized_0", "customized_0", "customized_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=runner._latest_test_results,
        )

    async def test_case_new_env_run_only_1_needed(self) -> None:
        # same predefined env as test_fit_a_bigger_env,
        # but all case want to run on a new env
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook, case_use_new_env=True)
        await runner.start()
        self.verify_env_results(
            expected_prepared=[
                "customized_0",
                "generated_1",
                "generated_2",
                "generated_3",
            ],
            expected_deployed_envs=["customized_0", "generated_1", "generated_3"],
            expected_deleted_envs=["customized_0", "generated_1", "generated_3"],
            runner=runner,
        )
        self.verify_test_results(
            expected_envs=["customized_0", "generated_1", "generated_3"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=runner._latest_test_results,
        )

    async def test_no_needed_env(self) -> None:
        # two 1 node env predefined, but only customized_0 go to deploy
        # no cases assigned to customized_1, as fit cases run on customized_0 already

        generate_cases_metadata()
        env_runbook = generate_env_runbook(local=True, remote=True)
        runner = generate_runner(env_runbook)
        await runner.start()
        self.verify_env_results(
            expected_prepared=[
                "customized_0",
                "customized_1",
                "generated_2",
                "generated_3",
            ],
            expected_deployed_envs=["customized_0", "generated_2"],
            expected_deleted_envs=["customized_0", "generated_2"],
            runner=runner,
        )
        self.verify_test_results(
            expected_envs=["generated_2", "customized_0", "customized_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=runner._latest_test_results,
        )

    async def test_deploy_no_more_resource(self) -> None:
        # platform may see no more resource, like no azure quota.
        # cases skipped due to this.
        # In future, will add retry on wait more resource.
        platform_schema = test_platform.MockPlatformSchema()
        platform_schema.wait_more_resource_error = True
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True)
        runner = generate_runner(env_runbook, platform_schema=platform_schema)
        await runner.start()

        self.verify_env_results(
            expected_prepared=[
                "customized_0",
                "generated_1",
                "generated_2",
                "generated_3",
            ],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
            runner=runner,
        )
        before_suite_failed = "no available environment"
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
            ],
            expected_message=[
                before_suite_failed,
                before_suite_failed,
                before_suite_failed,
            ],
            test_results=runner._latest_test_results,
        )

    async def test_skipped_on_suite_failure(self) -> None:
        # First two tests were skipped because the setup is made to fail.
        test_testsuite.fail_on_before_suite = True
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook)
        await runner.start()
        self.verify_env_results(
            expected_prepared=[
                "customized_0",
                "generated_1",
                "generated_2",
                "generated_3",
            ],
            expected_deployed_envs=["customized_0"],
            expected_deleted_envs=["customized_0"],
            runner=runner,
        )

        before_suite_failed = "before_suite: failed"
        self.verify_test_results(
            expected_envs=["customized_0", "customized_0", "customized_0"],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.PASSED,
            ],
            expected_message=[before_suite_failed, before_suite_failed, ""],
            test_results=runner._latest_test_results,
        )

    async def test_env_skipped_no_prepared_env(self) -> None:
        # test env not prepared, so test cases cannot find an env to run
        platform_schema = test_platform.MockPlatformSchema()
        platform_schema.return_prepared = False
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook, platform_schema=platform_schema)
        await runner.start()
        self.verify_env_results(
            expected_prepared=[
                "customized_0",
                "generated_1",
                "generated_2",
                "generated_3",
            ],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
            runner=runner,
        )

        no_available_env = "no available environment"
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
            ],
            expected_message=[no_available_env, no_available_env, no_available_env],
            test_results=runner._latest_test_results,
        )

    async def test_env_deploy_failed(self) -> None:
        # env prepared, but deployment failed
        # so cases failed also
        platform_schema = test_platform.MockPlatformSchema()
        platform_schema.deployed_status = EnvironmentStatus.Prepared
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook, platform_schema=platform_schema)
        await runner.start()
        self.verify_env_results(
            expected_prepared=[
                "customized_0",
                "generated_1",
                "generated_2",
                "generated_3",
            ],
            expected_deployed_envs=[
                "customized_0",
                "generated_1",
                "generated_3",
            ],
            expected_deleted_envs=[],
            runner=runner,
        )
        no_available_env = "deployment: expected status is EnvironmentStatus.Prepared"
        self.verify_test_results(
            expected_envs=["customized_0", "generated_1", "generated_3"],
            expected_status=[
                TestStatus.FAILED,
                TestStatus.FAILED,
                TestStatus.FAILED,
            ],
            expected_message=[no_available_env, no_available_env, no_available_env],
            test_results=runner._latest_test_results,
        )

    async def test_env_skipped_no_case(self) -> None:
        # no case found, as not call generate_case_metadata
        # in this case, not deploy any env
        env_runbook = generate_env_runbook(is_single_env=True, remote=True)
        runner = generate_runner(env_runbook)
        await runner.start()
        # still prepare predefined, but not deploy
        self.verify_env_results(
            expected_prepared=["customized_0"],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
            runner=runner,
        )
        self.verify_test_results(
            expected_envs=[],
            expected_status=[],
            expected_message=[],
            test_results=runner._latest_test_results,
        )

    def verify_test_results(
        self,
        expected_envs: List[str],
        expected_status: List[TestStatus],
        expected_message: List[str],
        test_results: List[TestResult],
    ) -> None:

        self.assertListEqual(
            expected_envs,
            [
                x.environment.name if x.environment is not None else ""
                for x in test_results
            ],
        )
        self.assertListEqual(
            expected_status,
            [x.status for x in test_results],
        )
        # compare it's begin with
        actual_messages = [
            test_results[index].message[0 : len(expected)]
            for index, expected in enumerate(expected_message)
        ]
        self.assertListEqual(
            expected_message,
            actual_messages,
        )

    def verify_env_results(
        self,
        expected_prepared: List[str],
        expected_deployed_envs: List[str],
        expected_deleted_envs: List[str],
        runner: Runner,
    ) -> None:
        platform = cast(test_platform.MockPlatform, runner._latest_platform)
        platform_test_data = platform.test_data

        self.assertListEqual(
            expected_prepared,
            list(platform_test_data.prepared_envs),
            "prepared envs inconstent",
        )
        self.assertListEqual(
            expected_deployed_envs,
            list(platform_test_data.deployed_envs),
            "deployed envs inconstent",
        )
        self.assertListEqual(
            expected_deleted_envs,
            list(platform_test_data.deleted_envs),
            "deleted envs inconstent",
        )
