# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, List, cast
from unittest import TestCase

from assertpy import assert_that

from lisa import LisaException, PassedException, SkippedException, constants, schema
from lisa.environment import EnvironmentStatus, load_environments
from lisa.operating_system import Posix, Windows
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.runner import parse_testcase_filters
from lisa.testselector import select_testcases
from lisa.testsuite import (
    TestCaseMetadata,
    TestCaseRuntimeData,
    TestResult,
    TestStatus,
    TestSuite,
    TestSuiteMetadata,
    get_cases_metadata,
    get_suites_metadata,
    node_requirement,
    simple_requirement,
)
from lisa.util.logger import Logger
from selftests.test_environment import generate_runbook

# for other UTs
fail_on_before_case = False
fail_on_after_case = False
partial_pass = False
skipped = False
queued = False
fail_case_count = 0
check_variable = False


class MockTestSuite(TestSuite):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_on_before_case = fail_on_before_case
        self.fail_on_after_case = fail_on_after_case
        self.partial_pass = partial_pass
        self.skipped = skipped
        self.queued = queued
        self.partial_pass = partial_pass
        self.fail_case_count = fail_case_count
        self.check_variable = check_variable

    def set_fail_phase(
        self,
        fail_on_before_case: bool = False,
        fail_on_after_case: bool = False,
        partial_pass: bool = False,
        skipped: bool = False,
        fail_case_count: int = 0,
        check_variable: bool = False,
    ) -> None:
        self.fail_on_before_case = fail_on_before_case
        self.fail_on_after_case = fail_on_after_case
        self.partial_pass = partial_pass
        self.skipped = skipped
        self.fail_case_count = fail_case_count
        self.check_variable = check_variable

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        if self.fail_on_before_case:
            raise LisaException("failed")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        if self.fail_on_after_case:
            raise LisaException("failed")

    def mock_ut1(self, *args: Any, **kwargs: Any) -> None:
        if self.partial_pass:
            raise PassedException("mock_ut1 passed with warning")
        if self.skipped:
            raise SkippedException("mock_ut1 skipped this run")
        while self.fail_case_count > 0:
            self.fail_case_count -= 1
            raise LisaException("mock_ut1 failed")

    def mock_ut2(self, variables: Dict[str, Any], **kwargs: Any) -> None:
        if self.check_variable:
            assert_that(variables).described_as("variable must exists").contains_entry(
                {"var": 1}
            )
        else:
            assert_that(variables).described_as("variable must not exists").is_empty()


class MockTestSuite2(TestSuite):
    def mock_ut3(self, *args: Any, **kwargs: Any) -> None:
        ...


def cleanup_cases_metadata() -> None:
    get_cases_metadata().clear()
    get_suites_metadata().clear()


def generate_cases_metadata() -> List[TestCaseMetadata]:
    ut_cases = [
        TestCaseMetadata(
            "ut1",
            0,
            requirement=simple_requirement(min_count=2),
        ),
        TestCaseMetadata("ut2", 1),
        TestCaseMetadata("ut3", 2),
    ]
    suite_metadata1 = TestSuiteMetadata("a1", "c1", "des1", ["t1", "t2"])
    suite_metadata1(MockTestSuite)
    ut_cases[0](MockTestSuite.mock_ut1)
    ut_cases[1](MockTestSuite.mock_ut2)

    suite_metadata2 = TestSuiteMetadata(
        "a2",
        "c2",
        "des2",
        ["t2", "t3"],
        requirement=node_requirement(node=schema.NodeSpace(core_count=8)),
    )
    suite_metadata2(MockTestSuite2)
    ut_cases[2](MockTestSuite2.mock_ut3)

    return ut_cases


def generate_cases_result() -> List[TestResult]:
    case_metadata = generate_cases_metadata()

    case_results = [TestResult("0", TestCaseRuntimeData(x)) for x in case_metadata]

    return case_results


def select_and_check(
    ut: TestCase, case_runbook: List[Any], expected_descriptions: List[str]
) -> List[TestCaseRuntimeData]:
    runbook = RunbookBuilder._validate_and_load({constants.TESTCASE: case_runbook})
    case_metadata = generate_cases_metadata()
    runbook.testcase = parse_testcase_filters(runbook.testcase_raw)
    filters = cast(List[schema.TestCase], runbook.testcase)
    selected = select_testcases(filters, case_metadata)
    ut.assertListEqual(expected_descriptions, [case.description for case in selected])

    return selected


class TestSuiteTestCase(TestCase):
    def generate_suite_instance(self) -> MockTestSuite:
        case_results = generate_cases_result()
        self.case_results = case_results[:2]
        suite_metadata = case_results[0].runtime_data.metadata.suite
        runbook = generate_runbook(is_single_env=True, local=True, remote=True)
        envs = load_environments(runbook)
        self.default_env = list(envs.values())[0]
        assert self.default_env
        test_suite = MockTestSuite(
            metadata=suite_metadata,
        )
        return test_suite

    def setUp(self) -> None:
        cleanup_cases_metadata()

    def test_expanded_nodespace(self) -> None:
        cases = generate_cases_metadata()
        for case in cases:
            self.assertIsNotNone(case.requirement)
            assert case.requirement.environment
            for node in case.requirement.environment.nodes:
                self.assertEqual(
                    1, node.node_count, "node count should be expanded to 1"
                )

    def test_case_override_suite(self) -> None:
        cases = generate_cases_metadata()
        case1_found = False
        case2_found = False
        for case in cases:
            assert case.requirement.environment
            assert case.suite.requirement.environment
            if case.name == "mock_ut1":
                self.assertEqual(2, len(case.requirement.environment.nodes))
                self.assertEqual(1, len(case.suite.requirement.environment.nodes))
                case1_found = True
            if case.name == "mock_ut2":
                self.assertEqual(1, len(case.requirement.environment.nodes))
                self.assertEqual(1, len(case.suite.requirement.environment.nodes))
                case2_found = True
        self.assertEqual(True, case1_found)
        self.assertEqual(True, case2_found)

    def test_test_result_canrun(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"priority": [0, 1, 2]}}]

        cases = select_and_check(self, runbook, ["ut1", "ut2", "ut3"])
        case = cases[0]
        for status in TestStatus:
            result = TestResult("0", case)
            result.set_status(status, f"set_{status}")
            self.assertEqual(f"set_{status}", result.message)
            self.assertEqual(status, result.status)
            if status == TestStatus.QUEUED:
                self.assertEqual(True, result.is_queued)
            else:
                self.assertEqual(False, result.is_queued)

    def test_variable_exists(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(check_variable=True)
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={"var": 1},
        )
        for result in self.case_results:
            self.assertEqual(TestStatus.PASSED, result.status)
            self.assertEqual("", result.message)

    def test_skip_before_case_failed(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(fail_on_before_case=True)
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={},
        )
        for result in self.case_results:
            self.assertEqual(TestStatus.SKIPPED, result.status)
            self.assertEqual("before_case: failed", result.message)

    def test_pass_after_case_failed(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(fail_on_after_case=True)
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={},
        )
        for result in self.case_results:
            self.assertEqual(TestStatus.PASSED, result.status)
            self.assertEqual("", result.message)

    def test_skip_case_failed(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(fail_case_count=1)
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={},
        )
        result = self.case_results[0]
        self.assertEqual(TestStatus.FAILED, result.status)
        self.assertEqual("failed. LisaException: mock_ut1 failed", result.message)
        result = self.case_results[1]
        self.assertEqual(TestStatus.PASSED, result.status)
        self.assertEqual("", result.message)

    def test_retry_passed(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(fail_case_count=1)
        result = self.case_results[0]
        result.runtime_data.retry = 1
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={},
        )
        self.assertEqual(TestStatus.PASSED, result.status)
        self.assertEqual("", result.message)
        result = self.case_results[1]
        self.assertEqual(TestStatus.PASSED, result.status)
        self.assertEqual("", result.message)

    def test_partial_passed(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(partial_pass=True)
        result = self.case_results[0]
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={},
        )
        self.assertEqual(TestStatus.PASSED, result.status)
        self.assertEqual("warning: mock_ut1 passed with warning", result.message)
        result = self.case_results[1]
        self.assertEqual(TestStatus.PASSED, result.status)
        self.assertEqual("", result.message)

    def test_skipped(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(skipped=True)
        result = self.case_results[0]
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={},
        )
        self.assertEqual(TestStatus.SKIPPED, result.status)
        self.assertEqual("skipped: mock_ut1 skipped this run", result.message)
        result = self.case_results[1]
        self.assertEqual(TestStatus.PASSED, result.status)
        self.assertEqual("", result.message)

    def test_retry_notenough_failed(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(fail_case_count=2)
        result = self.case_results[0]
        result.runtime_data.retry = 1
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={},
        )
        self.assertEqual(TestStatus.FAILED, result.status)
        self.assertEqual("failed. LisaException: mock_ut1 failed", result.message)
        result = self.case_results[1]
        self.assertEqual(TestStatus.PASSED, result.status)
        self.assertEqual("", result.message)

    def test_attempt_ignore_failure(self) -> None:
        test_suite = self.generate_suite_instance()
        test_suite.set_fail_phase(fail_case_count=2)
        result = self.case_results[0]
        result.runtime_data.ignore_failure = True
        test_suite.start(
            environment=self.default_env,
            case_results=self.case_results,
            case_variables={},
        )
        self.assertEqual(TestStatus.ATTEMPTED, result.status)
        self.assertEqual("mock_ut1 failed", result.message)
        result = self.case_results[1]
        self.assertEqual(TestStatus.PASSED, result.status)
        self.assertEqual("", result.message)

    def test_result_check_env_not_ready_os_type(self) -> None:
        _ = self.generate_suite_instance()
        assert self.default_env
        self.default_env.status = EnvironmentStatus.Deployed
        self.default_env._is_initialized = True
        for node in self.default_env.nodes.list():
            node.os = Posix(node)
        for result in self.case_results:
            check_result = result.check_environment(self.default_env)
            self.assertTrue(check_result)

    def test_result_check_env_os_type_not_unsupported(self) -> None:
        _ = self.generate_suite_instance()
        assert self.default_env
        self.default_env.status = EnvironmentStatus.Connected
        self.default_env._is_initialized = True
        case_metadata = self.case_results[0].runtime_data.metadata
        case_metadata.requirement = simple_requirement(
            min_count=2, unsupported_os=[Posix]
        )
        case_metadata = self.case_results[1].runtime_data.metadata
        case_metadata.requirement = simple_requirement(min_count=2, unsupported_os=[])
        for node in self.default_env.nodes.list():
            node.os = Windows(node)
        for result in self.case_results:
            check_result = result.check_environment(self.default_env)
            self.assertTrue(check_result)

    def test_result_check_env_os_type_supported(self) -> None:
        _ = self.generate_suite_instance()
        assert self.default_env
        self.default_env.status = EnvironmentStatus.Connected
        self.default_env._is_initialized = True
        case_metadata = self.case_results[0].runtime_data.metadata
        case_metadata.requirement = simple_requirement(
            min_count=2, supported_os=[Posix]
        )
        for node in self.default_env.nodes.list():
            node.os = Posix(node)
        for result in self.case_results:
            check_result = result.check_environment(self.default_env)
            self.assertTrue(check_result)

    def test_result_check_env_os_type_not_supported(self) -> None:
        _ = self.generate_suite_instance()
        assert self.default_env
        self.default_env.status = EnvironmentStatus.Connected
        self.default_env._is_initialized = True
        case_metadata = self.case_results[0].runtime_data.metadata
        case_metadata.requirement = simple_requirement(
            min_count=2, supported_os=[Posix]
        )
        case_metadata = self.case_results[1].runtime_data.metadata
        case_metadata.requirement = simple_requirement(
            min_count=2, supported_os=[Windows]
        )
        for node in self.default_env.nodes.list():
            node.os = Windows(node)
        with self.assertRaises(SkippedException) as cm:
            self.case_results[0].check_environment(self.default_env)
        self.assertEqual("OS type mismatch:", str(cm.exception)[:17])
        check_result = self.case_results[1].check_environment(self.default_env)
        self.assertTrue(check_result)

    def test_skipped_not_meet_req(self) -> None:
        _ = self.generate_suite_instance()
        assert self.default_env
        self.default_env.status = EnvironmentStatus.Deployed
        case_metadata = self.case_results[0].runtime_data.metadata
        case_metadata.requirement = simple_requirement(min_count=3)

        result = self.case_results[0]
        check_result = result.check_environment(self.default_env, save_reason=True)
        self.assertFalse(check_result)
        # only save reason, but not set final status, so that it can try next env
        self.assertEqual(TestStatus.QUEUED, result.status)
        assert result.check_results
        self.assertFalse(result.check_results.result)
        self.assertListEqual(
            ["no enough nodes, requirement: 3, capability: 2."],
            result.check_results.reasons,
        )
        result = self.case_results[1]
        check_result = result.check_environment(self.default_env, save_reason=True)
        self.assertTrue(check_result)
        self.assertEqual(TestStatus.QUEUED, result.status)
        assert result.check_results
        self.assertTrue(result.check_results.result)
        self.assertListEqual(
            [],
            result.check_results.reasons,
        )
