# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import traceback
from typing import Any, List, Optional, cast

from lisa import notifier, schema, search_space
from lisa.action import ActionStatus
from lisa.environment import (
    Environment,
    Environments,
    EnvironmentStatus,
    load_environments,
)
from lisa.platform_ import Platform, WaitMoreResourceError, load_platform
from lisa.runner import BaseRunner
from lisa.testselector import select_testcases
from lisa.testsuite import (
    TestCaseRequirement,
    TestResult,
    TestStatus,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.util import LisaException, constants


class LisaRunner(BaseRunner):
    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_LISA

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def _run(self, id_: str) -> List[TestResult]:
        # select test cases
        testcase_filters: List[schema.TestCase] = cast(
            List[schema.TestCase], self._runbook.testcase
        )
        selected_test_cases = select_testcases(testcase_filters)

        # create test results
        test_results = [
            TestResult(f"{id_}_{index}", runtime_data=case)
            for index, case in enumerate(selected_test_cases)
        ]

        run_message = notifier.TestRunMessage(
            status=notifier.TestRunStatus.RUNNING,
        )
        notifier.notify(run_message)

        # load predefined environments
        candidate_environments = load_environments(self._runbook.environment)

        platform = load_platform(self._runbook.platform)
        # get environment requirements
        self._merge_test_requirements(
            test_results=test_results,
            existing_environments=candidate_environments,
            platform_type=platform.type_name(),
        )

        # there may not need to handle requirements, if all environment are predefined

        prepared_environments = self._prepare_environments(
            platform=platform,
            candidate_environments=candidate_environments,
            test_results=test_results,
        )

        can_run_results = test_results
        # request environment then run tests
        for environment in prepared_environments:
            try:
                self._check_cancel()

                can_run_results = self._get_can_run_results(can_run_results)
                can_run_results.sort(key=lambda x: x.runtime_data.metadata.suite.name)
                if not can_run_results:
                    # no left tests, break the loop
                    self._log.debug(
                        f"no more test case to run, skip env [{environment.name}]"
                    )
                    continue

                # check if any test need this environment
                picked_result = self._pick_one_result_on_environment(
                    environment=environment, results=can_run_results
                )
                if picked_result is None:
                    self._log.debug(
                        f"env[{environment.name}] skipped "
                        f"as not meet any case requirement"
                    )
                    continue

                try:
                    platform.deploy_environment(environment)
                except WaitMoreResourceError as identifier:
                    self._log.info(
                        f"[{environment.name}] waiting for more resource: "
                        f"{identifier}, skip assigning case"
                    )
                    continue
                except Exception as identifier:
                    self._attach_failed_environment_to_result(
                        platform=platform,
                        environment=environment,
                        result=picked_result,
                        exception=identifier,
                    )
                    continue

                assert (
                    environment.status == EnvironmentStatus.Deployed
                ), f"actual: {environment.status}"

                self._log.info(f"start running cases on '{environment.name}'")

                # run test cases that need deployed environment
                self._run_cases_on_environment(
                    environment=environment, results=can_run_results
                )

                picked_result = self._pick_one_result_on_environment(
                    environment=environment, results=can_run_results
                )
                if picked_result is None:
                    self._log.debug(
                        f"env[{environment.name}] skipped initializing, "
                        f"since it doesn't meet any case requirement."
                    )
                    continue

                self._log.debug(f"initializing environment: {environment.name}")
                try:
                    environment.initialize()
                except Exception as identifier:
                    self._attach_failed_environment_to_result(
                        platform=platform,
                        environment=environment,
                        result=picked_result,
                        exception=identifier,
                    )
                    continue

                assert (
                    environment.status == EnvironmentStatus.Connected
                ), f"actual: {environment.status}"

                # run test cases that need connected environment
                self._run_cases_on_environment(
                    environment=environment, results=can_run_results
                )
            finally:
                if environment and environment.status in [
                    EnvironmentStatus.Deployed,
                    EnvironmentStatus.Connected,
                ]:
                    platform.delete_environment(environment)

        # not run as there is no fit environment.
        for case in self._get_can_run_results(can_run_results):
            reasons = "no available environment"
            if case.check_results and case.check_results.reasons:
                reasons = f"{reasons}: {case.check_results.reasons}"

            case.set_status(TestStatus.SKIPPED, reasons)

        self.status = ActionStatus.SUCCESS

        # for UT testability
        self._latest_platform = platform

        return test_results

    def _prepare_environments(
        self,
        platform: Platform,
        candidate_environments: Environments,
        test_results: List[TestResult],
    ) -> List[Environment]:
        prepared_environments: List[Environment] = []
        for candidate_environment in candidate_environments.values():
            try:
                prepared_environment = platform.prepare_environment(
                    candidate_environment
                )
                prepared_environments.append(prepared_environment)
            except Exception as identifier:
                matched_result = self._pick_one_result_on_environment(
                    environment=candidate_environment, results=test_results
                )
                if not matched_result:
                    self._log.info(
                        "No requirement of test case is suitable for the preparation "
                        f"error of the environment '{candidate_environment.name}'. "
                        "Randomly attach a test case to this environment. "
                        "This may be because the platform failed before populating the "
                        "features into this environment.",
                    )
                    matched_result = next(
                        (result for result in test_results if result.can_run),
                        None,
                    )
                if not matched_result:
                    raise LisaException(
                        "There are no remaining test results to run, so preparation "
                        "errors cannot be appended to the test results. Please correct "
                        "the error and run again. "
                        f"original exception: {identifier}"
                    )
                self._attach_failed_environment_to_result(
                    platform=platform,
                    environment=candidate_environment,
                    result=matched_result,
                    exception=identifier,
                )

        # sort by environment source and cost cases
        # user defined should be higher priority than test cases' requirement
        prepared_environments.sort(key=lambda x: (not x.is_predefined, x.cost))

        return prepared_environments

    def _pick_one_result_on_environment(
        self, environment: Environment, results: List[TestResult]
    ) -> Optional[TestResult]:
        return next(
            (
                case
                for case in self._get_can_run_results(results)
                if case.check_environment(environment, True)
            ),
            None,
        )

    def _run_cases_on_environment(
        self, environment: Environment, results: List[TestResult]
    ) -> None:

        self._log.debug(
            f"start running cases on '{environment.name}', "
            f"status {environment.status.name}"
        )
        # try a case need new environment firstly
        if environment.is_new:
            for new_env_result in self._get_can_run_results(
                results, use_new_environment=True, environment_status=environment.status
            ):
                self._check_cancel()
                if new_env_result.check_environment(environment, True):
                    self._run_suite(
                        environment=environment, case_results=[new_env_result]
                    )
                    break

        # grouped test results by test suite.
        grouped_cases: List[TestResult] = []
        current_test_suite: Optional[TestSuiteMetadata] = None
        for test_result in self._get_can_run_results(
            results, use_new_environment=False, environment_status=environment.status
        ):
            self._check_cancel()
            if test_result.check_environment(environment, True):
                if (
                    test_result.runtime_data.metadata.suite != current_test_suite
                    and grouped_cases
                ):
                    # run last batch cases
                    self._run_suite(environment=environment, case_results=grouped_cases)
                    grouped_cases = []

                # append new test cases
                current_test_suite = test_result.runtime_data.metadata.suite
                grouped_cases.append(test_result)

        if grouped_cases:
            self._run_suite(environment=environment, case_results=grouped_cases)

    def _run_suite(
        self, environment: Environment, case_results: List[TestResult]
    ) -> None:

        assert case_results
        suite_metadata = case_results[0].runtime_data.metadata.suite
        test_suite: TestSuite = suite_metadata.test_class(
            suite_metadata,
        )
        test_suite.start(environment=environment, case_results=case_results)

    def _attach_failed_environment_to_result(
        self,
        platform: Platform,
        environment: Environment,
        result: TestResult,
        exception: Exception,
    ) -> None:
        # make first fit test case failed by deployment,
        # so deployment failure can be tracked.
        environment.platform = platform
        result.environment = environment
        result.set_status(TestStatus.FAILED, f"deployment: {str(exception)}")
        self._log.lines(
            logging.DEBUG,
            "".join(
                traceback.format_exception(
                    etype=type(exception),
                    value=exception,
                    tb=exception.__traceback__,
                )
            ),
        )
        self._log.info(
            f"'{environment.name}' attached to test case "
            f"'{result.runtime_data.metadata.full_name}': "
            f"{exception}"
        )

    def _get_can_run_results(
        self,
        source_results: List[TestResult],
        use_new_environment: Optional[bool] = None,
        environment_status: Optional[EnvironmentStatus] = None,
    ) -> List[TestResult]:
        results = [
            x
            for x in source_results
            if x.can_run
            and (
                use_new_environment is None
                or x.runtime_data.use_new_environment == use_new_environment
            )
            and (
                environment_status is None
                or x.runtime_data.metadata.requirement.environment_status
                == environment_status
            )
        ]
        return results

    def _merge_test_requirements(
        self,
        test_results: List[TestResult],
        existing_environments: Environments,
        platform_type: str,
    ) -> None:
        assert platform_type
        platform_type_set = search_space.SetSpace[str](
            is_allow_set=True, items=[platform_type]
        )
        for test_result in test_results:
            test_req: TestCaseRequirement = test_result.runtime_data.requirement

            # check if there is playform requirement on test case
            if test_req.platform_type and len(test_req.platform_type) > 0:
                check_result = test_req.platform_type.check(platform_type_set)
                if not check_result.result:
                    test_result.set_status(TestStatus.SKIPPED, check_result.reasons)

            if test_result.can_run:
                assert test_req.environment
                # if case need a new env to run, force to create one.
                # if not, get or create one.
                if test_result.runtime_data.use_new_environment:
                    existing_environments.from_requirement(test_req.environment)
                else:
                    existing_environments.get_or_create(test_req.environment)

    def _check_cancel(self) -> None:
        if self.canceled:
            raise LisaException("received cancellation from root runner")
