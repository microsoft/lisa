from typing import Any, Dict, List, Optional, cast

from lisa import schema
from lisa.action import Action, ActionStatus
from lisa.environment import Environment, Environments, load_environments
from lisa.platform_ import WaitMoreResourceError, platforms
from lisa.testselector import select_testcases
from lisa.testsuite import (
    TestCaseRequirement,
    TestCaseRuntimeData,
    TestResult,
    TestStatus,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.util import constants
from lisa.util.logger import get_logger


class LISARunner(Action):
    def __init__(self) -> None:
        super().__init__()
        self.exitCode = None

        self._log = get_logger("runner")

    @property
    def typename(self) -> str:
        return "LISA"

    def config(self, key: str, value: Any) -> None:
        if key == constants.CONFIG_RUNBOOK:
            self._runbook = cast(schema.Runbook, value)

    async def start(self) -> None:
        await super().start()
        self.set_status(ActionStatus.RUNNING)

        # select test cases
        selected_cases = select_testcases(self._runbook.testcase)

        # create test results
        selected_case_results = self._create_test_results(selected_cases)

        # load predefined environments
        candidate_environments = load_environments(self._runbook.environment)

        platform = platforms.default
        # get environment requirements
        self._get_env_requirements(
            case_results=selected_case_results,
            existing_environments=candidate_environments,
            platform_type=platform.platform_type(),
        )

        # there may not need to handle requirements, if all environment are predefined
        platform.prepare_environments(candidate_environments)

        for environment in list(candidate_environments.values()):
            if environment.priority < 0:
                self._log.debug(
                    f"environment [{environment.name}] "
                    f"dropped by platform [{platform.platform_type()}]"
                )
                del candidate_environments[environment.name]

        # sort test cases
        planned_environments = list(candidate_environments.values())
        planned_environments.sort(key=lambda x: x.priority)

        can_run_results = selected_case_results
        # request environment then run test case
        for environment in planned_environments:
            try:
                is_needed: bool = False
                can_run_results = [x for x in can_run_results if x.can_run]
                can_run_results.sort(key=lambda x: x.runtime_data.metadata.suite.name)
                new_env_can_run_results = [
                    x for x in can_run_results if x.runtime_data.use_new_environment
                ]

                if not can_run_results:
                    # no left cases, break the loop
                    self._log.debug("no more case to run")
                    break

                # check if any case need this environment
                for case in can_run_results:
                    if case.can_run:
                        if case.check_environment(environment, True):
                            is_needed = True
                            break
                if not is_needed:
                    self._log.debug(
                        f"env[{environment.name}] skipped "
                        f"as not meet any case requirement"
                    )
                    continue

                try:
                    platform.deploy_environment(environment)
                except WaitMoreResourceError as identifier:
                    self._log.warn(
                        f"[{environment.name}] waiting for more resource: {identifier}"
                    )
                    continue

                if not environment.is_ready:
                    self._log.warn(
                        f"environment {environment.name} is not deployed successfully"
                    )
                    continue

                # once environment is ready, check updated capability
                self._log.info(f"start running cases on {environment.name}")
                # try a case need new environment firstly
                for new_env_result in new_env_can_run_results:
                    if new_env_result.check_environment(environment, True):
                        await self._run_suite(
                            environment=environment, cases=[new_env_result]
                        )
                        break

                # grouped test results by test suite.
                grouped_cases: List[TestResult] = []
                current_test_suite: Optional[TestSuiteMetadata] = None
                for test_result in can_run_results:
                    if (
                        test_result.can_run
                        and test_result.check_environment(environment, True)
                        and not test_result.runtime_data.use_new_environment
                    ):
                        if (
                            test_result.runtime_data.metadata.suite
                            != current_test_suite
                            and grouped_cases
                        ):
                            # run last batch cases
                            await self._run_suite(
                                environment=environment, cases=grouped_cases
                            )
                            grouped_cases = []

                        # append new test cases
                        current_test_suite = test_result.runtime_data.metadata.suite
                        grouped_cases.append(test_result)

                if grouped_cases:
                    await self._run_suite(environment=environment, cases=grouped_cases)
            finally:
                if environment and environment.is_ready:
                    platform.delete_environment(environment)

        # not run as there is no fit environment.
        for case in can_run_results:
            if case.can_run:
                assert case.check_results
                case.set_status(
                    TestStatus.SKIPPED,
                    f"no environment meet requirement: {case.check_results.reasons}",
                )

        result_count_dict: Dict[TestStatus, int] = dict()
        for result in selected_case_results:
            self._log.info(
                f"{result.runtime_data.metadata.full_name:>30}: "
                f"{result.status.name:<8} {result.message}"
            )
            result_count = result_count_dict.get(result.status, 0)
            result_count += 1
            result_count_dict[result.status] = result_count

        self._log.info("result summary")
        self._log.info(f"  TOTAL      : {len(selected_case_results)}")
        for key in TestStatus:
            self._log.info(f"    {key.name:<9}: {result_count_dict.get(key, 0)}")

        # delete enviroment after run
        self.set_status(ActionStatus.SUCCESS)

    async def stop(self) -> None:
        super().stop()

    async def close(self) -> None:
        super().close()

    async def _run_suite(
        self, environment: Environment, cases: List[TestResult]
    ) -> None:

        assert cases
        suite_metadata = cases[0].runtime_data.metadata.suite
        test_suite: TestSuite = suite_metadata.test_class(
            environment, cases, suite_metadata,
        )
        try:
            await test_suite.start()
        except Exception as identifier:
            self._log.error(f"suite[{suite_metadata.name}] failed: {identifier}")
            for case in cases:
                if case.can_run:
                    case.set_status(TestStatus.SKIPPED, "test suite setup failed")

    def _create_test_results(
        self, cases: List[TestCaseRuntimeData]
    ) -> List[TestResult]:
        test_results: List[TestResult] = []
        for x in cases:
            test_results.append(TestResult(runtime_data=x))
        return test_results

    def _get_env_requirements(
        self,
        case_results: List[TestResult],
        existing_environments: Environments,
        platform_type: str,
    ) -> Dict[str, List[TestResult]]:
        env_case_map: Dict[str, List[TestResult]] = dict()

        for predefined_env in existing_environments.values():
            env_case_map[predefined_env.name] = []

        for case_result in case_results:
            case_req: TestCaseRequirement = case_result.runtime_data.requirement
            if case_req.platform_type:
                check_result = case_req.platform_type.check(platform_type)
                if not check_result.result:
                    case_result.set_status(TestStatus.SKIPPED, check_result.reasons)

            if case_result.can_run:
                assert case_req.environment
                need_new_env = case_result.runtime_data.use_new_environment
                if need_new_env:
                    environment = existing_environments.from_requirement(
                        case_req.environment
                    )
                else:
                    environment = existing_environments.get_or_create(
                        case_req.environment
                    )
                if environment:
                    req_cases = env_case_map.get(environment.name, [])
                    req_cases.append(case_result)
                    env_case_map[environment.name] = req_cases
                else:
                    case_result.set_status(
                        TestStatus.SKIPPED,
                        "not found fit environment, "
                        "and not allow to create new environment",
                    )

        return env_case_map
