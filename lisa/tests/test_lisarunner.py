import asyncio
from typing import List, Optional
from unittest.case import TestCase

from lisa import schema
from lisa.environment import load_environments
from lisa.lisarunner import LisaRunner
from lisa.tests import test_platform, test_testsuite
from lisa.tests.test_environment import generate_runbook as generate_env_runbook
from lisa.tests.test_platform import deleted_envs, deployed_envs, prepared_envs
from lisa.tests.test_testsuite import (
    cleanup_cases_metadata,
    generate_cases_metadata,
    generate_cases_result,
)
from lisa.testsuite import TestResult, TestStatus, simple_requirement
from lisa.util import constants


def generate_lisarunner(
    env_runbook: Optional[schema.EnvironmentRoot] = None, case_use_new_env: bool = False
) -> LisaRunner:
    runbook = schema.Runbook(
        platform=[
            schema.Platform(type=constants.PLATFORM_MOCK, admin_password="not use it")
        ],
        testcase=[
            schema.TestCase(
                criteria=schema.Criteria(priority=[0, 1, 2]),
                use_new_environment=case_use_new_env,
            )
        ],
    )
    if env_runbook:
        runbook.environment = env_runbook
    runner = LisaRunner(runbook)

    return runner


class LisaRunnerTestCase(TestCase):
    def tearDown(self) -> None:
        cleanup_cases_metadata()
        test_platform.return_prepared = True
        test_platform.deploy_is_ready = True
        test_platform.deploy_success = True
        test_platform.wait_more_resource_error = False

    def test_merge_req_create_on_new(self) -> None:
        # if no predefined envs, can generate from requirement
        env_runbook = generate_env_runbook(is_single_env=False)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [],
            [x for x in envs],
        )
        runner = generate_lisarunner(None)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # 3 cases create 3 envs
        self.assertListEqual(
            ["req_0", "req_1", "req_2"],
            [x for x in envs],
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
            ["runbook_0"],
            [x for x in envs],
        )

        runner = generate_lisarunner(env_runbook)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )

        # 3 cases created only two req, as simple req meets on runbook_0
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2"],
            [x for x in envs],
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
            ["runbook_0"],
            [x for x in envs],
        )
        runner = generate_lisarunner(env_runbook)
        test_results = generate_cases_result()
        for test_result in test_results:
            test_result.runtime_data.use_new_environment = True
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # every case need a new environment, so created 3
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"],
            [x for x in envs],
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
            [x for x in envs],
        )
        runner = generate_lisarunner(None)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertListEqual(
            [],
            [x for x in envs],
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
            [x for x in envs],
        )
        runner = generate_lisarunner(None)
        test_results = generate_cases_result()
        for test_result in test_results:
            metadata = test_result.runtime_data.metadata
            metadata.requirement = simple_requirement(
                supported_platform_type=["notexists"]
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

    def test_fit_a_predefined_env(self) -> None:
        # predefined env can run case in below condition.
        # 1. with predefined env of 1 simple node, so ut2 don't need a new env
        # 2. ut3 need 8 cores, and predefined env target to meet all core requirement,
        #    so it can run any case with core requirements.
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2"],
            expected_deployed_envs=["runbook_0", "req_1"],
            expected_deleted_envs=["runbook_0", "req_1"],
        )
        self.verify_test_results(
            expected_envs=["req_1", "runbook_0", "runbook_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=runner._latest_test_results,
        )

    def test_fit_a_bigger_env(self) -> None:
        # similar with test_fit_a_predefined_env, but predefined 2 nodes,
        # it doesn't equal to any case req, but reusable for all cases.
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0"],
            expected_deleted_envs=["runbook_0"],
        )
        self.verify_test_results(
            expected_envs=["runbook_0", "runbook_0", "runbook_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=runner._latest_test_results,
        )

    def test_case_new_env_run_only_1_needed(self) -> None:
        # same predefined env as test_fit_a_bigger_env,
        # but all case want to run on a new env
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook, case_use_new_env=True)
        asyncio.run(runner.start())
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0", "req_1", "req_3"],
            expected_deleted_envs=["runbook_0", "req_1", "req_3"],
        )
        self.verify_test_results(
            expected_envs=["runbook_0", "req_1", "req_3"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=runner._latest_test_results,
        )

    def test_no_needed_env(self) -> None:
        # two 1 node env predefined, but only runbook_0 go to deploy
        # no cases assigned to runbook_1, as fit cases run on runbook_0 already
        generate_cases_metadata()
        env_runbook = generate_env_runbook(local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.verify_env_results(
            expected_prepared=["runbook_0", "runbook_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0", "req_2"],
            expected_deleted_envs=["runbook_0", "req_2"],
        )
        self.verify_test_results(
            expected_envs=["req_2", "runbook_0", "runbook_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=runner._latest_test_results,
        )

    def test_deploy_no_more_resource(self) -> None:
        # platform may see no more resource, like no azure quota.
        # cases skipped due to this.
        # In future, will add retry on wait more resource.
        test_platform.wait_more_resource_error = True
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())

        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
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

    def test_skipped_on_suite_failure(self) -> None:
        # first two cases skipped due to test suite setup failed
        test_testsuite.fail_on_before_suite = True
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0"],
            expected_deleted_envs=["runbook_0"],
        )
        before_suite_failed = "before_suite: failed"
        self.verify_test_results(
            expected_envs=["runbook_0", "runbook_0", "runbook_0"],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.PASSED,
            ],
            expected_message=[before_suite_failed, before_suite_failed, ""],
            test_results=runner._latest_test_results,
        )

    def test_env_skipped_no_prepared_env(self) -> None:
        # test env not prepared, so test cases cannot find an env to run
        test_platform.return_prepared = False
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
        )
        no_avaiable_env = "no available environment"
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
            ],
            expected_message=[no_avaiable_env, no_avaiable_env, no_avaiable_env],
            test_results=runner._latest_test_results,
        )

    def test_env_skipped_not_ready(self) -> None:
        # env prepared, but not deployed to ready.
        # so no cases can run
        test_platform.deploy_is_ready = False
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deleted_envs=[],
        )
        no_avaiable_env = "no available environment"
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
            ],
            expected_message=[no_avaiable_env, no_avaiable_env, no_avaiable_env],
            test_results=runner._latest_test_results,
        )

    def test_env_skipped_no_case(self) -> None:
        # no case found, as not call generate_case_metadata
        # in this case, not deploy any env
        env_runbook = generate_env_runbook(is_single_env=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        # still prepare predefined, but not deploy
        self.verify_env_results(
            expected_prepared=["runbook_0"],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
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
            [x.env for x in test_results],
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
    ) -> None:
        self.assertListEqual(
            expected_prepared,
            [x for x in prepared_envs],
        )
        self.assertListEqual(
            expected_deployed_envs,
            [x for x in deployed_envs],
        )
        self.assertListEqual(
            expected_deleted_envs,
            [x for x in deleted_envs],
        )
