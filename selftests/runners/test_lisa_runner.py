# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Optional, Union, cast
from unittest import TestCase

import lisa
from lisa import LisaException, constants, schema
from lisa.environment import EnvironmentStatus, load_environments
from lisa.messages import TestResultMessage, TestStatus
from lisa.notifier import register_notifier
from lisa.runner import RunnerResult
from lisa.runners.lisa_runner import LisaRunner
from lisa.testsuite import TestResult, simple_requirement
from lisa.util.parallel import Task
from selftests import test_platform, test_testsuite
from selftests.test_environment import generate_runbook as generate_env_runbook


def generate_runner(
    env_runbook: Optional[schema.EnvironmentRoot] = None,
    case_use_new_env: bool = False,
    times: int = 1,
    platform_schema: Optional[test_platform.MockPlatformSchema] = None,
) -> LisaRunner:
    platform_runbook = schema.Platform(
        type=constants.PLATFORM_MOCK, admin_password="do-not-use"
    )
    if platform_schema:
        platform_runbook.extended_schemas = {
            constants.PLATFORM_MOCK: platform_schema.to_dict()  # type:ignore
        }
    runbook = schema.Runbook(
        platform=[platform_runbook],
    )
    runbook.testcase = [
        schema.TestCase(
            criteria=schema.Criteria(priority=[0, 1, 2]),
            use_new_environment=case_use_new_env,
            times=times,
        )
    ]
    if env_runbook:
        runbook.environment = env_runbook
    runner = LisaRunner(runbook, 0, {})

    return runner


class RunnerTestCase(TestCase):
    __skipped_no_env = "no available environment"

    def setUp(self) -> None:
        lisa.environment._global_environment_id = 0

    def tearDown(self) -> None:
        test_testsuite.cleanup_cases_metadata()  # Necessary side effects!

    def test_merge_req_create_on_new(self) -> None:
        # if no predefined envs, can generate from requirement
        env_runbook = generate_env_runbook(is_single_env=False)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [],
            [x for x in envs],
        )
        runner = generate_runner(None)
        test_results = test_testsuite.generate_cases_result()
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
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["", "", ""],
            expected_status=[TestStatus.QUEUED, TestStatus.QUEUED, TestStatus.QUEUED],
            expected_message=["", "", ""],
            test_results=test_results,
        )

    def test_merge_req(self) -> None:
        # each test case will create an environment candidate.
        env_runbook = generate_env_runbook(remote=True)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            ["customized_0"],
            list(envs),
        )
        runner = generate_runner(env_runbook)

        test_results = test_testsuite.generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertListEqual(
            ["customized_0", "generated_1", "generated_2", "generated_3"],
            list(envs),
        )
        self.assertListEqual(
            [
                TestStatus.QUEUED,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
            ],
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

        test_results = test_testsuite.generate_cases_result()
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
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["", "", ""],
            expected_status=[TestStatus.QUEUED, TestStatus.QUEUED, TestStatus.QUEUED],
            expected_message=["", "", ""],
            test_results=test_results,
        )

    def test_merge_req_all_generated(self) -> None:
        # force to use existing env, not to create new.
        # this case doesn't provide predefined env, but no case skipped on this stage.
        env_runbook = generate_env_runbook(is_single_env=False)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [],
            list(envs),
        )
        runner = generate_runner(None)
        test_results = test_testsuite.generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertListEqual(
            ["generated_0", "generated_1", "generated_2"],
            list(envs),
        )

        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.QUEUED,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
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
        test_results = test_testsuite.generate_cases_result()
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
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
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

    def test_fit_a_predefined_env(self) -> None:
        # predefined env can run case in below condition.
        # 1. with predefined env of 1 simple node, so ut2 don't need a new env
        # 2. ut3 need 8 cores, and predefined env target to meet all core requirement,
        #    so it can run any case with core requirements.
        test_testsuite.generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, remote=True)
        runner = generate_runner(env_runbook)
        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=["customized_0"],
            expected_deployed_envs=["customized_0"],
            expected_deleted_envs=["customized_0"],
            runner=runner,
        )

        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["", "customized_0", "customized_0"],
            expected_status=[TestStatus.SKIPPED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=[self.__skipped_no_env, "", ""],
            test_results=test_results,
        )

    def test_fit_a_bigger_env(self) -> None:
        # similar with test_fit_a_predefined_env, but predefined 2 nodes,
        # it doesn't equal to any case req, but reusable for all cases.

        test_testsuite.generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook)
        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=["customized_0"],
            expected_deployed_envs=["customized_0"],
            expected_deleted_envs=["customized_0"],
            runner=runner,
        )
        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["customized_0", "customized_0", "customized_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=test_results,
        )

    def test_case_new_env_run_only_1_needed_customized(self) -> None:
        # same predefined env as test_fit_a_bigger_env,
        # but all case want to run on a new env
        test_testsuite.generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook, case_use_new_env=True)
        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=["customized_0"],
            expected_deployed_envs=["customized_0"],
            expected_deleted_envs=["customized_0"],
            runner=runner,
        )
        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["customized_0", "", ""],
            expected_status=[TestStatus.PASSED, TestStatus.SKIPPED, TestStatus.SKIPPED],
            expected_message=["", self.__skipped_no_env, self.__skipped_no_env],
            test_results=test_results,
        )

    def test_case_new_env_run_only_1_needed_generated(self) -> None:
        # same predefined env as test_fit_a_bigger_env,
        # but all case want to run on a new env
        test_testsuite.generate_cases_metadata()
        env_runbook = generate_env_runbook()
        runner = generate_runner(env_runbook, case_use_new_env=True, times=2)
        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=[
                "generated_0",
                "generated_1",
                "generated_2",
                "generated_3",
                "generated_4",
                "generated_5",
            ],
            expected_deployed_envs=[
                "generated_0",
                "generated_1",
                "generated_2",
                "generated_3",
                "generated_4",
                "generated_5",
            ],
            expected_deleted_envs=[
                "generated_0",
                "generated_1",
                "generated_2",
                "generated_3",
                "generated_4",
                "generated_5",
            ],
            runner=runner,
        )
        self.verify_test_results(
            expected_test_order=[
                "mock_ut1",
                "mock_ut1",
                "mock_ut2",
                "mock_ut2",
                "mock_ut3",
                "mock_ut3",
            ],
            expected_envs=[
                "generated_0",
                "generated_1",
                "generated_2",
                "generated_3",
                "generated_4",
                "generated_5",
            ],
            expected_status=[
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.PASSED,
            ],
            expected_message=["", "", "", "", "", ""],
            test_results=test_results,
        )

    def test_no_needed_env(self) -> None:
        # two 1 node env predefined, but only customized_0 go to deploy
        # no cases assigned to customized_1, as fit cases run on customized_0 already

        test_testsuite.generate_cases_metadata()
        env_runbook = generate_env_runbook(local=True, remote=True)
        runner = generate_runner(env_runbook)
        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=[
                "customized_0",
                "customized_1",
            ],
            expected_deployed_envs=["customized_0"],
            expected_deleted_envs=["customized_0"],
            runner=runner,
        )

        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["", "customized_0", "customized_0"],
            expected_status=[TestStatus.SKIPPED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=[self.__skipped_no_env, "", ""],
            test_results=test_results,
        )

    def test_deploy_no_more_resource(self) -> None:
        # platform may see no more resource, like no azure quota.
        # cases skipped due to this.
        # In future, will add retry on wait more resource.
        platform_schema = test_platform.MockPlatformSchema()
        platform_schema.wait_more_resource_error = True
        test_testsuite.generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True)
        runner = generate_runner(env_runbook, platform_schema=platform_schema)
        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=["customized_0"],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
            runner=runner,
        )
        no_more_resource_message = "no more resource to deploy"
        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
            ],
            expected_message=[
                self.__skipped_no_env,
                no_more_resource_message,
                no_more_resource_message,
            ],
            test_results=test_results,
        )

    def test_skipped_on_suite_failure(self) -> None:
        # First two tests were skipped because the setup is made to fail.
        test_testsuite.fail_on_before_suite = True
        test_testsuite.generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook)
        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=["customized_0"],
            expected_deployed_envs=["customized_0"],
            expected_deleted_envs=["customized_0"],
            runner=runner,
        )

        before_suite_failed = "before_suite: failed"
        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["customized_0", "customized_0", "customized_0"],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.PASSED,
            ],
            expected_message=[before_suite_failed, before_suite_failed, ""],
            test_results=test_results,
        )

    def test_env_failed_not_prepared_env(self) -> None:
        # test env not prepared, so test cases cannot find an env to run
        platform_schema = test_platform.MockPlatformSchema()
        platform_schema.return_prepared = False
        test_testsuite.generate_cases_metadata()
        runner = generate_runner(None, platform_schema=platform_schema)

        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=[
                "generated_0",
                "generated_1",
                "generated_2",
            ],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
            runner=runner,
        )

        no_available_env = (
            "deployment failed. LisaException: no capability found for environment: "
        )
        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=[
                "generated_0",
                "generated_1",
                "generated_2",
            ],
            expected_status=[
                TestStatus.FAILED,
                TestStatus.FAILED,
                TestStatus.FAILED,
            ],
            expected_message=[
                no_available_env,
                no_available_env,
                no_available_env,
            ],
            test_results=test_results,
        )

    def test_env_failed_more_failed_env_on_prepare(self) -> None:
        # test env not prepared, so test cases cannot find an env to run
        platform_schema = test_platform.MockPlatformSchema()
        platform_schema.return_prepared = False
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_runner(env_runbook, platform_schema=platform_schema)

        with self.assertRaises(LisaException) as cm:
            _ = self._run_all_tests(runner)
        self.assertIn(
            "There are no remaining test results to run, ",
            str(cm.exception),
        )

    def test_env_deploy_failed(self) -> None:
        # env prepared, but deployment failed, so cases failed
        platform_schema = test_platform.MockPlatformSchema()
        platform_schema.deployed_status = EnvironmentStatus.Prepared
        test_testsuite.generate_cases_metadata()
        env_runbook = generate_env_runbook()
        runner = generate_runner(env_runbook, platform_schema=platform_schema)
        test_results = self._run_all_tests(runner)

        self.verify_env_results(
            expected_prepared=[
                "generated_0",
                "generated_1",
                "generated_2",
            ],
            expected_deployed_envs=[
                "generated_0",
                "generated_1",
                "generated_2",
            ],
            expected_deleted_envs=[
                "generated_0",
                "generated_1",
                "generated_2",
            ],
            runner=runner,
        )
        no_available_env = (
            "deployment failed. LisaException: "
            "expected status is EnvironmentStatus.Prepared"
        )
        self.verify_test_results(
            expected_test_order=["mock_ut1", "mock_ut2", "mock_ut3"],
            expected_envs=["generated_0", "generated_1", "generated_2"],
            expected_status=[
                TestStatus.FAILED,
                TestStatus.FAILED,
                TestStatus.FAILED,
            ],
            expected_message=[no_available_env, no_available_env, no_available_env],
            test_results=test_results,
        )

    def test_env_skipped_no_case(self) -> None:
        # no case found, as not call generate_case_metadata
        # in this case, not deploy any env
        env_runbook = generate_env_runbook(is_single_env=True, remote=True)
        runner = generate_runner(env_runbook)
        test_results = self._run_all_tests(runner)

        # still prepare predefined, but not deploy
        self.verify_env_results(
            expected_prepared=["customized_0"],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
            runner=runner,
        )
        self.verify_test_results(
            expected_test_order=[],
            expected_envs=[],
            expected_status=[],
            expected_message=[],
            test_results=test_results,
        )

    def verify_test_results(
        self,
        expected_test_order: List[str],
        expected_envs: List[str],
        expected_status: List[TestStatus],
        expected_message: List[str],
        test_results: Union[List[TestResultMessage], List[TestResult]],
    ) -> None:

        test_names: List[str] = []
        env_names: List[str] = []
        for test_result in test_results:
            if isinstance(test_result, TestResult):
                test_names.append(test_result.runtime_data.metadata.name)
                env_names.append(
                    test_result.environment.name
                    if test_result.environment is not None
                    else ""
                )
            else:
                assert isinstance(test_result, TestResultMessage)
                test_names.append(test_result.full_name.split(".")[1])
                env_names.append(test_result.information.get("environment", ""))
        self.assertListEqual(
            expected_test_order,
            test_names,
            "test order inconsistent",
        )
        self.assertListEqual(
            expected_envs,
            env_names,
            "test env inconsistent",
        )
        self.assertListEqual(
            expected_status,
            [x.status for x in test_results],
            "test result inconsistent",
        )
        # compare it's begin with
        actual_messages = [
            test_results[index].message[0 : len(expected)]
            for index, expected in enumerate(expected_message)
        ]
        self.assertListEqual(
            expected_message,
            actual_messages,
            "test message inconsistent",
        )

    def verify_env_results(
        self,
        expected_prepared: List[str],
        expected_deployed_envs: List[str],
        expected_deleted_envs: List[str],
        runner: LisaRunner,
    ) -> None:
        platform = cast(test_platform.MockPlatform, runner.platform)
        platform_test_data = platform.test_data

        self.assertListEqual(
            expected_prepared,
            list(platform_test_data.prepared_envs),
            "prepared envs inconsistent",
        )
        self.assertListEqual(
            expected_deployed_envs,
            list(platform_test_data.deployed_envs),
            "deployed envs inconsistent",
        )
        self.assertListEqual(
            expected_deleted_envs,
            list(platform_test_data.deleted_envs),
            "deleted envs inconsistent",
        )

    def _run_all_tests(self, runner: LisaRunner) -> List[TestResultMessage]:
        results_collector = RunnerResult(schema.Notifier())
        register_notifier(results_collector)

        runner.initialize()

        while not runner.is_done:
            task = runner.fetch_task()
            if task:
                if isinstance(task, Task):
                    task()

        return [x for x in results_collector.results.values()]
