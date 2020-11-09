import logging
import traceback
from typing import Dict, List, Optional

from lisa import notifier, schema, search_space
from lisa.action import Action, ActionStatus
from lisa.environment import (
    Environment,
    Environments,
    EnvironmentStatus,
    load_environments,
)
from lisa.platform_ import WaitMoreResourceError, load_platform
from lisa.testselector import select_testcases
from lisa.testsuite import (
    TestCaseRequirement,
    TestResult,
    TestStatus,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.util.logger import get_logger


class Runner(Action):
    def __init__(self, runbook: schema.Runbook) -> None:
        super().__init__()
        self.exit_code: int = 0

        self._runbook = runbook
        self._log = get_logger("runner")

    # TODO: This entire function is one long string of side-effects.
    async def start(self) -> None:
        await super().start()

        # select test cases
        selected_test_cases = select_testcases(self._runbook.testcase)

        # create test results
        test_results = [TestResult(runtime_data=case) for case in selected_test_cases]

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
        prepared_environments = platform.prepare_environments(candidate_environments)

        run_message = notifier.TestRunMessage(
            status=notifier.TestRunStatus.RUNNING,
        )
        notifier.notify(run_message)

        can_run_results = test_results
        # request environment then run tests
        for environment in prepared_environments:
            try:
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
                    self._log.warning(
                        f"[{environment.name}] waiting for more resource: "
                        f"{identifier}, skip assiging case"
                    )
                    continue
                except Exception as identifier:
                    self._attach_failed_environment_to_result(
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
                await self._run_cases_on_environment(
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
                        environment=environment,
                        result=picked_result,
                        exception=identifier,
                    )
                    continue

                assert (
                    environment.status == EnvironmentStatus.Connected
                ), f"actual: {environment.status}"

                # run test cases that need connected environment
                await self._run_cases_on_environment(
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

        self._output_results(test_results)

        self.status = ActionStatus.SUCCESS

        # pass failed count to exit code
        self.exit_code = sum(1 for x in test_results if x.status == TestStatus.FAILED)

        # for UT testability
        self._latest_platform = platform
        self._latest_test_results = test_results

    async def stop(self) -> None:
        super().stop()

    async def close(self) -> None:
        super().close()

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

    async def _run_cases_on_environment(
        self, environment: Environment, results: List[TestResult]
    ) -> None:

        self._log.debug(
            f"start running cases on '{environment.name}', "
            f"status {environment.status.name}"
        )
        # try a case need new environment firstly
        if environment.is_new:
            for new_env_result in self._get_can_run_results(
                results, use_new_environment=True, enviornment_status=environment.status
            ):
                if new_env_result.check_environment(environment, True):
                    await self._run_suite(
                        environment=environment, results=[new_env_result]
                    )
                    break

        # grouped test results by test suite.
        grouped_cases: List[TestResult] = []
        current_test_suite: Optional[TestSuiteMetadata] = None
        for test_result in self._get_can_run_results(
            results, use_new_environment=False, enviornment_status=environment.status
        ):
            if test_result.check_environment(environment, True):
                if (
                    test_result.runtime_data.metadata.suite != current_test_suite
                    and grouped_cases
                ):
                    # run last batch cases
                    await self._run_suite(
                        environment=environment, results=grouped_cases
                    )
                    grouped_cases = []

                # append new test cases
                current_test_suite = test_result.runtime_data.metadata.suite
                grouped_cases.append(test_result)

        if grouped_cases:
            await self._run_suite(environment=environment, results=grouped_cases)

    async def _run_suite(
        self, environment: Environment, results: List[TestResult]
    ) -> None:

        assert results
        suite_metadata = results[0].runtime_data.metadata.suite
        test_suite: TestSuite = suite_metadata.test_class(
            environment,
            results,
            suite_metadata,
        )
        for result in results:
            result.environment = environment
        environment.is_new = False
        await test_suite.start()

    def _attach_failed_environment_to_result(
        self, environment: Environment, result: TestResult, exception: Exception
    ) -> None:
        # make first fit test case fail by deployment
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
        enviornment_status: Optional[EnvironmentStatus] = None,
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
                enviornment_status is None
                or x.runtime_data.metadata.requirement.environment_status
                == enviornment_status
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

    def _output_results(self, test_results: List[TestResult]) -> None:
        self._log.info("________________________________________")
        result_count_dict: Dict[TestStatus, int] = dict()
        for test_result in test_results:
            self._log.info(
                f"{test_result.runtime_data.metadata.full_name:>50}: "
                f"{test_result.status.name:<8} {test_result.message}"
            )
            result_count = result_count_dict.get(test_result.status, 0)
            result_count += 1
            result_count_dict[test_result.status] = result_count

        self._log.info("test result summary")
        self._log.info(f"  TOTAL      : {len(test_results)}")
        for key in TestStatus:
            count = result_count_dict.get(key, 0)
            if key == TestStatus.ATTEMPTED and count == 0:
                # attempted is confusing, if user don't know it.
                # so hide it, if there is no attempted cases.
                continue
            self._log.info(f"    {key.name:<9}: {count}")
