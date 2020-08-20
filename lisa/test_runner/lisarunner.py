from typing import Dict, Iterable, List, cast

from lisa.action import Action, ActionStatus
from lisa.environment import environments
from lisa.platform_ import Platform
from lisa.testsuite import (
    TestCaseData,
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
        return "LISAv2"

    def config(self, key: str, value: object) -> None:
        if key == constants.CONFIG_PLATFORM:
            self.platform = cast(Platform, value)
        if key == constants.CONFIG_TEST_CASES:
            self.cases = cast(Iterable[TestCaseData], value)

    async def start(self) -> None:
        await super().start()
        self.set_status(ActionStatus.RUNNING)

        # select test cases
        test_results: List[TestResult] = []
        test_suites: Dict[TestSuiteMetadata, List[TestResult]] = dict()
        for test_case_data in self.cases:
            test_result = TestResult(case=test_case_data)
            test_results.append(test_result)
            test_suite_cases = test_suites.get(test_case_data.metadata.suite, [])
            test_suite_cases.append(test_result)
            test_suites[test_case_data.metadata.suite] = test_suite_cases

        # request environment
        environment = self.platform.request_environment(environments.default)

        self._log.info(f"start running {len(test_results)} cases")
        for test_suite_data in test_suites:
            test_suite: TestSuite = test_suite_data.test_class(
                environment, test_suites.get(test_suite_data, []), test_suite_data
            )
            try:
                await test_suite.start()
            except Exception as identifier:
                self._log.error(f"suite[{test_suite_data}] failed: {identifier}")

        result_count_dict: Dict[TestStatus, int] = dict()
        for result in test_results:
            result_count = result_count_dict.get(result.status, 0)
            result_count += 1
            result_count_dict[result.status] = result_count

        self._log.info("result summary")
        self._log.info(f"    TOTAL\t: {len(test_results)}")
        for key in TestStatus:
            self._log.info(f"    {key.name}\t: {result_count_dict.get(key, 0)}")

        # delete enviroment after run
        self.platform.delete_environment(environment)
        self.set_status(ActionStatus.SUCCESS)

    async def stop(self) -> None:
        super().stop()

    async def close(self) -> None:
        super().close()
