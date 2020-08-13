from typing import Dict, List, cast

from lisa.core.actionStatus import ActionStatus
from lisa.core.environmentFactory import EnvironmentFactory
from lisa.core.platform import Platform
from lisa.core.testFactory import TestFactory, TestSuiteData
from lisa.core.testResult import TestResult, TestStatus
from lisa.core.testRunner import TestRunner
from lisa.core.testSuite import TestSuite
from lisa.util import constants
from lisa.util.logger import log


class LISARunner(TestRunner):
    def __init__(self) -> None:
        super().__init__()
        self.exitCode = None

    @property
    def typename(self) -> str:
        return "LISAv2"

    def config(self, key: str, value: object) -> None:
        if key == constants.CONFIG_PLATFORM:
            self.platform: Platform = cast(Platform, value)

    async def start(self) -> None:
        await super().start()
        self.set_status(ActionStatus.RUNNING)
        test_factory = TestFactory()
        suites = test_factory.suites

        # select test cases
        test_cases_results: List[TestResult] = []
        test_suites: Dict[TestSuiteData, List[TestResult]] = dict()
        for test_suite_data in suites.values():
            for test_case_data in test_suite_data.cases.values():
                test_result = TestResult(case=test_case_data)
                test_cases_results.append(test_result)
                test_suite_cases = test_suites.get(test_case_data.suite, [])
                test_suite_cases.append(test_result)
                test_suites[test_case_data.suite] = test_suite_cases

        environment_factory = EnvironmentFactory()
        platform_type = self.platform.platform_type()
        # request environment
        log.info(f"platform {platform_type} environment requesting")
        environment = environment_factory.get_environment()
        log.info(f"platform {platform_type} environment requested")

        log.info(f"start running {len(test_cases_results)} cases")
        for test_suite_data in test_suites:
            test_suite: TestSuite = test_suite_data.test_class(
                environment, test_suites.get(test_suite_data, []), test_suite_data
            )
            try:
                await test_suite.start()
            except Exception as identifier:
                log.error(f"suite[{test_suite_data}] failed: {identifier}")

        result_count_dict: Dict[TestStatus, int] = dict()
        for result in test_cases_results:
            result_count = result_count_dict.get(result.status, 0)
            result_count += 1
            result_count_dict[result.status] = result_count

        log.info("result summary")
        log.info(f"    TOTAL\t: {len(test_cases_results)} ")
        for key in TestStatus:
            log.info(f"    {key.name}\t: {result_count_dict.get(key, 0)} ")

        # delete enviroment after run
        log.info(f"platform {platform_type} environment {environment.name} deleting")
        self.platform.delete_environment(environment)
        log.info(f"platform {platform_type} environment {environment.name} deleted")

        self.set_status(ActionStatus.SUCCESS)

    async def stop(self) -> None:
        super().stop()

    async def close(self) -> None:
        super().close()
