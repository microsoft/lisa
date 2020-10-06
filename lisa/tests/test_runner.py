from typing import Any, List
from unittest import IsolatedAsyncioTestCase

import lisa.runner
from lisa import schema
from lisa.environment import load_environments
from lisa.tests import test_platform, test_testsuite
from lisa.tests.test_environment import generate_runbook
from lisa.tests.test_platform import deleted_envs, deployed_envs, prepared_envs
from lisa.tests.test_testsuite import (
    cleanup_cases_metadata,
    generate_cases_metadata,
    generate_cases_result,
)
from lisa.testsuite import TestResult, TestStatus, simple_requirement
from lisa.util import constants


def generate_test_runbook(
    case_use_new_env: bool = False, **kwargs: Any
) -> schema.Runbook:
    """This wraps `generate_runbook` with a mock platform and test case."""
    return schema.Runbook(
        platform=[
            schema.Platform(type=constants.PLATFORM_MOCK, admin_password="do-not-use")
        ],
        testcase=[
            schema.TestCase(
                criteria=schema.Criteria(priority=[0, 1, 2]),
                use_new_environment=case_use_new_env,
            )
        ],
        environment=generate_runbook(**kwargs),
    )


class RunnerTestCase(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        cleanup_cases_metadata()  # Necessary side effects!
        test_platform.return_prepared = True
        test_platform.deploy_is_ready = True
        test_platform.deploy_success = True
        test_platform.wait_more_resource_error = False

    def test_merge_req_create_on_new(self) -> None:
        """Create environments based on requirements."""
        envs = load_environments(generate_runbook(is_single_env=False))
        self.assertFalse(envs)
        test_results = generate_cases_result()
        lisa.runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # 3 cases create 3 environments.
        self.assertListEqual(
            ["req_0", "req_1", "req_2"],
            list(envs),
        )
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            expected_message=["", "", ""],
            test_results=test_results,
        )

    def test_merge_req_run_not_create_on_equal(self) -> None:
        """Don't create environments when already satisfied."""
        envs = load_environments(generate_runbook(remote=True))
        self.assertListEqual(
            ["runbook_0"],
            list(envs),
        )
        test_results = generate_cases_result()
        lisa.runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # 3 cases created only two required environments, as the
        # simple requirement was met by runbook_0.
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2"],
            list(envs),
        )
        self.assertListEqual(
            [TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            [x.status for x in test_results],
        )

    def test_merge_req_create_on_use_new(self) -> None:
        """Always create environments when asked."""
        envs = load_environments(generate_runbook(remote=True))
        self.assertListEqual(
            ["runbook_0"],
            list(envs),
        )
        test_results = generate_cases_result()
        for test_result in test_results:
            test_result.runtime_data.use_new_environment = True
        lisa.runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # All 3 cases needed a new environment, so it created 3.
        self.assertListEqual(
            ["runbook_0", "req_1", "req_2", "req_3"],
            list(envs),
        )
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[TestStatus.NOTRUN, TestStatus.NOTRUN, TestStatus.NOTRUN],
            expected_message=["", "", ""],
            test_results=test_results,
        )

    def test_merge_req_not_allow_create(self) -> None:
        """Do not create an existing environment when not allowed."""
        runbook = generate_runbook(is_single_env=False)
        runbook.allow_create = False
        envs = load_environments(runbook)
        self.assertFalse(envs)
        test_results = generate_cases_result()
        lisa.runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        self.assertFalse(envs)
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
        """Ensure the platform check happens.

        For example, some cases run only on Azure. A simple check is
        sufficient because more is covered by `search_space.SetSpace`.
        """
        envs = load_environments(generate_runbook(is_single_env=False))
        self.assertFalse(envs)
        test_results = generate_cases_result()
        for test_result in test_results:
            metadata = test_result.runtime_data.metadata
            metadata.requirement = simple_requirement(
                supported_platform_type=["does-not-exist"]
            )
        lisa.runner._merge_test_requirements(
            test_results=test_results,
            existing_environments=envs,
            platform_type=constants.PLATFORM_MOCK,
        )
        # TODO: This message should be in a localization module of
        # some sort.
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
        """Pre-defined environments can run with the conditions:

        1. With pre-defined environment of 1 simple node, unit test 2
        doesn't need a new environment.

        2. Unit test 3 needs 8 cores, but the pre-defined environment
        has these and so can run all the tests.

        """
        # TODO: This function call is necessary, which means that it
        # sets some unknown global state. We need to fix those side
        # effects because this is unintelligible.
        generate_cases_metadata()
        runbook = generate_test_runbook(is_single_env=True, remote=True)
        results = await lisa.runner.run(runbook)
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2"],
            expected_deployed_envs=["runbook_0", "req_1"],
            expected_deleted_envs=["runbook_0", "req_1"],
        )
        self.verify_test_results(
            expected_envs=["req_1", "runbook_0", "runbook_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=results,
        )

    async def test_fit_a_bigger_env(self) -> None:
        """Similar to `test_fit_a_predefined_env` but with pre-defined 2 nodes.

        While it doesn't exactly match any requirement, it's re-usable
        for every test.

        """
        generate_cases_metadata()
        runbook = generate_test_runbook(is_single_env=True, local=True, remote=True)
        results = await lisa.runner.run(runbook)
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0"],
            expected_deleted_envs=["runbook_0"],
        )
        self.verify_test_results(
            expected_envs=["runbook_0", "runbook_0", "runbook_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=results,
        )

    async def test_case_new_env_run_only_1_needed(self) -> None:
        """Same as `test_fit_a_bigger_env` but we require a new environment."""
        generate_cases_metadata()
        runbook = generate_test_runbook(
            case_use_new_env=True, is_single_env=True, local=True, remote=True
        )
        results = await lisa.runner.run(runbook)
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0", "req_1", "req_3"],
            expected_deleted_envs=["runbook_0", "req_1", "req_3"],
        )
        self.verify_test_results(
            expected_envs=["runbook_0", "req_1", "req_3"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=results,
        )

    async def test_no_needed_env(self) -> None:
        """No new environments need to be created.

        Two single-node environments are pre-defined, and only
        `runbook_0` is deployed. The environment for `runbook_1` is
        not deployed because its tests were able to run on the
        environment deployed for `runbook_0`.

        """
        generate_cases_metadata()
        runbook = generate_test_runbook(local=True, remote=True)
        results = await lisa.runner.run(runbook)
        self.verify_env_results(
            expected_prepared=["runbook_0", "runbook_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0", "req_2"],
            expected_deleted_envs=["runbook_0", "req_2"],
        )
        self.verify_test_results(
            expected_envs=["req_2", "runbook_0", "runbook_0"],
            expected_status=[TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
            expected_message=["", "", ""],
            test_results=results,
        )

    async def test_deploy_no_more_resource(self) -> None:
        """Skip tests if resources quotas were hit.

        TODO: In the future, we may add retry logic to wait on
        resources becoming available.

        """
        test_platform.wait_more_resource_error = True
        generate_cases_metadata()
        runbook = generate_test_runbook(is_single_env=True, local=True)
        results = await lisa.runner.run(runbook)
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
            test_results=results,
        )

    async def test_skipped_on_suite_failure(self) -> None:
        """First two tests were skipped because the setup is made to fail."""
        test_testsuite.fail_on_before_suite = True
        generate_cases_metadata()
        runbook = generate_test_runbook(is_single_env=True, local=True, remote=True)
        results = await lisa.runner.run(runbook)
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0"],
            expected_deleted_envs=["runbook_0"],
        )
        # TODO: This message should be in a localization module of
        # some sort.
        before_suite_failed = "before_suite: failed"
        self.verify_test_results(
            expected_envs=["runbook_0", "runbook_0", "runbook_0"],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.PASSED,
            ],
            expected_message=[before_suite_failed, before_suite_failed, ""],
            test_results=results,
        )

    async def test_env_skipped_no_prepared_env(self) -> None:
        """The platform's environment isn't prepared so the tests cannot run."""
        test_platform.return_prepared = False
        generate_cases_metadata()
        runbook = generate_test_runbook(is_single_env=True, local=True, remote=True)
        results = await lisa.runner.run(runbook)
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
        )
        # TODO: This message should be in a localization module of
        # some sort.
        no_available_env = "no available environment"
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
            ],
            expected_message=[no_available_env, no_available_env, no_available_env],
            test_results=results,
        )

    async def test_env_skipped_not_ready(self) -> None:
        """The prepared environment is not deployed, so tests are skipped."""
        test_platform.deploy_is_ready = False
        generate_cases_metadata()
        runbook = generate_test_runbook(is_single_env=True, local=True, remote=True)
        results = await lisa.runner.run(runbook)
        self.verify_env_results(
            expected_prepared=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deployed_envs=["runbook_0", "req_1", "req_2", "req_3"],
            expected_deleted_envs=[],
        )
        # TODO: This message should be in a localization module of
        # some sort.
        no_available_env = "no available environment"
        self.verify_test_results(
            expected_envs=["", "", ""],
            expected_status=[
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
                TestStatus.SKIPPED,
            ],
            expected_message=[no_available_env, no_available_env, no_available_env],
            test_results=results,
        )

    async def test_env_skipped_no_case(self) -> None:
        """TODO: Investigate why `generate_case_metadata` side effects matter."""
        runbook = generate_test_runbook(is_single_env=True, remote=True)
        results = await lisa.runner.run(runbook)
        self.verify_env_results(
            expected_prepared=["runbook_0"],
            expected_deployed_envs=[],
            expected_deleted_envs=[],
        )
        self.verify_test_results(
            expected_envs=[],
            expected_status=[],
            expected_message=[],
            test_results=results,
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
        """TODO: Explain why this function works and what it does."""
        self.assertListEqual(expected_prepared, list(prepared_envs))
        self.assertListEqual(expected_deployed_envs, list(deployed_envs))
        self.assertListEqual(expected_deleted_envs, list(deleted_envs))
