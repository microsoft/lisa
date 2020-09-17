import asyncio
from typing import Optional
from unittest.case import TestCase

from lisa import schema
from lisa.environment import load_environments
from lisa.test_runner.lisarunner import LisaRunner
from lisa.tests import test_platform, test_testsuite
from lisa.tests.test_environment import generate_runbook as generate_env_runbook
from lisa.tests.test_platform import deleted_envs, deployed_envs, prepared_envs
from lisa.tests.test_testsuite import (
    cleanup_cases_metadata,
    generate_cases_metadata,
    generate_cases_result,
)
from lisa.testsuite import TestStatus, simple_requirement
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
    runner = LisaRunner()
    runner.config(constants.CONFIG_RUNBOOK, runbook)

    return runner


class LisaRunnerTestCase(TestCase):
    def tearDown(self) -> None:
        cleanup_cases_metadata()
        test_platform.return_prepared = True
        test_platform.deploy_is_ready = True
        test_platform.deploy_success = True
        test_platform.wait_more_resource_error = False

    def test_merge_req_run_not_create_on_equal(self) -> None:
        env_runbook = generate_env_runbook(remote=True)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            ["runbook_0"], [x for x in envs],
        )
        runner = generate_lisarunner(env_runbook)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2"], [x for x in envs],
        )
        self.assertListEqual(
            [TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            [x.status for x in test_results],
        )

    def test_merge_req_create_on_new(self) -> None:
        env_runbook = generate_env_runbook(is_single_env=False)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [], [x for x in envs],
        )
        runner = generate_lisarunner(None)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertListEqual(
            ["req_0", "req_1", "req_2"], [x for x in envs],
        )
        self.assertListEqual(
            [TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            [x.status for x in test_results],
        )

    def test_merge_req_create_on_use_new(self) -> None:
        env_runbook = generate_env_runbook(remote=True)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            ["runbook_0"], [x for x in envs],
        )
        runner = generate_lisarunner(env_runbook)
        test_results = generate_cases_result()
        # every test case need a new environment, so must to create
        for test_result in test_results:
            test_result.runtime_data.use_new_environment = True
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"], [x for x in envs],
        )
        self.assertListEqual(
            [TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            [x.status for x in test_results],
        )

    def test_merge_req_not_allow_create(self) -> None:
        env_runbook = generate_env_runbook(is_single_env=False)
        env_runbook.allow_create = False
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [], [x for x in envs],
        )
        runner = generate_lisarunner(None)
        test_results = generate_cases_result()
        runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertListEqual(
            [], [x for x in envs],
        )
        self.assertListEqual(
            [TestStatus.SKIPPED, TestStatus.SKIPPED, TestStatus.SKIPPED],
            [x.status for x in test_results],
        )
        not_allow_new_message = (
            "not found fit environment, and not allow to create new environment"
        )
        self.assertListEqual(
            [not_allow_new_message, not_allow_new_message, not_allow_new_message],
            [x.message for x in test_results],
        )

    def test_merge_req_platform_type_checked(self) -> None:
        # checked is enough. More covered in search space
        env_runbook = generate_env_runbook(is_single_env=False)
        envs = load_environments(env_runbook)
        self.assertListEqual(
            [], [x for x in envs],
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
        self.assertListEqual(
            [TestStatus.SKIPPED, TestStatus.SKIPPED, TestStatus.SKIPPED],
            [x.status for x in test_results],
        )
        platform_unsupported = "capability cannot support some of requirement"
        self.assertListEqual(
            [platform_unsupported, platform_unsupported, platform_unsupported],
            [x.message[0:45] for x in test_results],
        )

    def test_fit_a_predefined_env(self) -> None:
        # with predefined env of 1 simple node, so ut2 don't need a new env
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2"], [x for x in prepared_envs],
        )
        self.assertListEqual(
            ["runbook_0", "req_1"], [x for x in deployed_envs],
        )
        self.assertListEqual(
            ["runbook_0", "req_1"], [x for x in deleted_envs],
        )
        self.assertListEqual(
            ["req_1", "runbook_0", "runbook_0"],
            [x.assigned_env for x in runner._latest_test_results],
        )
        self.assertListEqual(
            [TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            [x.status for x in runner._latest_test_results],
        )
        self.assertListEqual(
            ["", "", ""], [x.message for x in runner._latest_test_results],
        )

    def test_fit_a_bigger_env(self) -> None:
        # with predefined env of 2 nodes, it doesn't equal to any case req,
        # but reusable for all
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"], [x for x in prepared_envs],
        )
        self.assertListEqual(
            ["runbook_0"], [x for x in deployed_envs],
        )
        self.assertListEqual(
            ["runbook_0"], [x for x in deleted_envs],
        )
        self.assertListEqual(
            ["runbook_0", "runbook_0", "runbook_0"],
            [x.assigned_env for x in runner._latest_test_results],
        )
        self.assertListEqual(
            [TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            [x.status for x in runner._latest_test_results],
        )
        self.assertListEqual(
            ["", "", ""], [x.message for x in runner._latest_test_results],
        )

    def test_case_new_env_run_only_1_needed(self) -> None:
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook, case_use_new_env=True)
        asyncio.run(runner.start())
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"], [x for x in prepared_envs],
        )
        # compare with test_fit_a_bigger_env, each env run only 1 test case.
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2"], [x for x in deployed_envs],
        )
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2"], [x for x in deleted_envs],
        )
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2"],
            [x.assigned_env for x in runner._latest_test_results],
        )
        self.assertListEqual(
            [TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            [x.status for x in runner._latest_test_results],
        )
        self.assertListEqual(
            ["", "", ""], [x.message for x in runner._latest_test_results],
        )

    def test_no_needed_env(self) -> None:
        # remote env is not used and req_3 (8 core)
        generate_cases_metadata()
        env_runbook = generate_env_runbook(local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.assertListEqual(
            ["runbook_0", "runbook_1", "req_2", "req_3"], [x for x in prepared_envs],
        )
        self.assertListEqual(
            ["runbook_0", "req_2"], [x for x in deployed_envs],
        )
        self.assertListEqual(
            ["runbook_0", "req_2"], [x for x in deleted_envs],
        )
        self.assertListEqual(
            ["req_2", "runbook_0", "runbook_0"],
            [x.assigned_env for x in runner._latest_test_results],
        )
        self.assertListEqual(
            [TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            [x.status for x in runner._latest_test_results],
        )
        self.assertListEqual(
            ["", "", ""], [x.message for x in runner._latest_test_results],
        )

    def test_deploy_no_more_resource(self) -> None:
        test_platform.wait_more_resource_error = True
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"], [x for x in prepared_envs],
        )
        self.assertListEqual(
            [], [x for x in deployed_envs],
        )
        self.assertListEqual(
            [], [x for x in deleted_envs],
        )
        self.assertListEqual(
            ["", "", ""], [x.assigned_env for x in runner._latest_test_results],
        )
        self.assertListEqual(
            [TestStatus.SKIPPED, TestStatus.SKIPPED, TestStatus.SKIPPED],
            [x.status for x in runner._latest_test_results],
        )
        before_suite_failed = "no available environment"
        self.assertListEqual(
            [before_suite_failed, before_suite_failed, before_suite_failed],
            [x.message[0:24] for x in runner._latest_test_results],
        )

    def test_skipped_on_suite_failure(self) -> None:
        # first two cases skipped due to init failed
        test_testsuite.fail_on_before_suite = True
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"], [x for x in prepared_envs],
        )
        self.assertListEqual(
            ["runbook_0"], [x for x in deployed_envs],
        )
        self.assertListEqual(
            ["runbook_0"], [x for x in deleted_envs],
        )
        self.assertListEqual(
            ["runbook_0", "runbook_0", "runbook_0"],
            [x.assigned_env for x in runner._latest_test_results],
        )
        self.assertListEqual(
            [TestStatus.SKIPPED, TestStatus.SKIPPED, TestStatus.PASSED],
            [x.status for x in runner._latest_test_results],
        )
        before_suite_failed = "before_suite: failed"
        self.assertListEqual(
            [before_suite_failed, before_suite_failed, ""],
            [x.message for x in runner._latest_test_results],
        )

    def test_env_skipped_no_prepared_env(self) -> None:
        test_platform.return_prepared = False
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"], [x for x in prepared_envs],
        )
        self.assertListEqual(
            [], [x for x in deployed_envs],
        )
        self.assertListEqual(
            [], [x for x in deleted_envs],
        )
        self.assertListEqual(
            ["", "", ""], [x.assigned_env for x in runner._latest_test_results],
        )
        self.assertListEqual(
            [TestStatus.SKIPPED, TestStatus.SKIPPED, TestStatus.SKIPPED],
            [x.status for x in runner._latest_test_results],
        )
        no_avaiable_env = "no available environment"
        self.assertListEqual(
            [no_avaiable_env, no_avaiable_env, no_avaiable_env],
            [x.message for x in runner._latest_test_results],
        )

    def test_env_skipped_not_ready(self) -> None:
        test_platform.deploy_is_ready = False
        generate_cases_metadata()
        env_runbook = generate_env_runbook(is_single_env=True, local=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"], [x for x in prepared_envs],
        )
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"], [x for x in deployed_envs],
        )
        self.assertListEqual(
            [], [x for x in deleted_envs],
        )
        self.assertListEqual(
            ["", "", ""], [x.assigned_env for x in runner._latest_test_results],
        )
        self.assertListEqual(
            [TestStatus.SKIPPED, TestStatus.SKIPPED, TestStatus.SKIPPED],
            [x.status for x in runner._latest_test_results],
        )
        no_avaiable_env = "no available environment"
        self.assertListEqual(
            [no_avaiable_env, no_avaiable_env, no_avaiable_env],
            [x.message[0:24] for x in runner._latest_test_results],
        )

    def test_env_skipped_no_case(self) -> None:
        # not generate_case_metadata, so no case here
        env_runbook = generate_env_runbook(is_single_env=True, remote=True)
        runner = generate_lisarunner(env_runbook)
        asyncio.run(runner.start())
        # still prepare predefined, but not deploy
        self.assertListEqual(
            ["runbook_0"], [x for x in prepared_envs],
        )
        self.assertListEqual(
            [], [x for x in deployed_envs],
        )
        self.assertListEqual(
            [], [x for x in deleted_envs],
        )
