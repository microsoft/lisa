from typing import Any, List
from unittest import TestCase

from lisa.parameter_parser.runbook import validate_data
from lisa.testselector import select_testcases
from lisa.testsuite import (
    TestCaseData,
    TestCaseMetadata,
    TestSuiteMetadata,
    _cases,
    _suites,
)
from lisa.util import LisaException, constants


class SelectorTestCase(TestCase):
    def setUp(self) -> None:
        _cases.clear()
        _suites.clear()

    def test_no_case_selected(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"area": "demo"}}]
        self._select_and_check(runbook, [])

    def test_skip_not_enabled(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tag": "t2"}, constants.ENABLE: False},
            {constants.TESTCASE_CRITERIA: {"tag": "t3"}},
        ]
        self._select_and_check(runbook, ["ut3"])

    def test_select_by_priroity(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"priority": 0}}]
        self._select_and_check(runbook, ["ut1"])

    def test_select_by_tag(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"tag": "t1"}}]
        self._select_and_check(runbook, ["ut1", "ut2"])

    def test_select_by_one_of_tag(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"tag": ["t1", "t3"]}}]
        self._select_and_check(runbook, ["ut1", "ut2", "ut3"])

    def test_select_by_two_rules(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"tag": ["t1", "t3"], "area": "a1"}}]
        self._select_and_check(runbook, ["ut1", "ut2"])

    def test_select_by_two_criteria(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"name": "mock_ut1"}},
            {constants.TESTCASE_CRITERIA: {"name": "mock_ut2"}},
        ]
        self._select_and_check(runbook, ["ut1", "ut2"])

    def test_select_then_drop(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tag": "t1"}},
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "exclude",
            },
        ]
        self._select_and_check(runbook, ["ut1"])

    def test_select_drop_select(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tag": "t1"}},
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "exclude",
            },
            {constants.TESTCASE_CRITERIA: {"tag": "t1"}},
        ]
        self._select_and_check(runbook, ["ut1", "ut2"])

    def test_select_force_include(self) -> None:
        runbook = [
            {
                constants.TESTCASE_CRITERIA: {"tag": "t1"},
                constants.TESTCASE_SELECT_ACTION: "forceInclude",
            },
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "exclude",
            },
        ]
        self._select_and_check(runbook, ["ut1", "ut2"])

    def test_select_force_conflict(self) -> None:
        runbook = [
            {
                constants.TESTCASE_CRITERIA: {"tag": "t1"},
                constants.TESTCASE_SELECT_ACTION: "forceInclude",
            },
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "forceExclude",
            },
        ]
        with self.assertRaises(LisaException) as cm:
            self._select_and_check(runbook, ["ut1", "ut2"])
        self.assertIsInstance(cm.exception, LisaException)
        self.assertIn("force", str(cm.exception))

    def test_select_force_conflict_exclude(self) -> None:
        runbook = [
            {
                constants.TESTCASE_CRITERIA: {"tag": "t1"},
                constants.TESTCASE_SELECT_ACTION: "include",
            },
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "forceExclude",
            },
            {
                constants.TESTCASE_CRITERIA: {"tag": "t1"},
                constants.TESTCASE_SELECT_ACTION: "forceInclude",
            },
        ]
        with self.assertRaises(LisaException) as cm:
            self._select_and_check(runbook, [])
            self.assertIsInstance(cm.exception, LisaException)
            self.assertIn("force", str(cm.exception))

    def test_select_with_setting(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tag": "t1"}, "times": 2},
        ]
        selected = self._select_and_check(runbook, ["ut1", "ut2"])

        self.assertListEqual([2, 2], [case.times for case in selected])

    def test_select_with_setting_none(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tag": "t1"}},
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                "times": 2,
                constants.TESTCASE_SELECT_ACTION: "none",
            },
        ]
        selected = self._select_and_check(runbook, ["ut1", "ut2"])
        self.assertListEqual([1, 2], [case.times for case in selected])

    def test_select_with_diff_setting(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tag": "t1"}, "times": 2},
            {constants.TESTCASE_CRITERIA: {"name": "mock_ut2"}, "times": 3},
        ]
        selected = self._select_and_check(runbook, ["ut1", "ut2"])

        self.assertListEqual([2, 3], [case.times for case in selected])

    def _select_and_check(
        self, case_runbook: List[Any], expected_descriptions: List[str]
    ) -> List[TestCaseData]:
        runbook = validate_data({constants.TESTCASE: case_runbook})
        case_metadatas = self._generate_metadata()
        selected = select_testcases(runbook.testcase, case_metadatas)
        self.assertListEqual(
            expected_descriptions, [case.description for case in selected]
        )

        return selected

    def _generate_metadata(self) -> List[TestCaseMetadata]:
        ut_cases = [
            TestCaseMetadata("ut1", 0),
            TestCaseMetadata("ut2", 1),
            TestCaseMetadata("ut3", 2),
        ]
        suite_metadata1 = TestSuiteMetadata("a1", "c1", "des1", ["t1", "t2"])
        suite_metadata2 = TestSuiteMetadata("a2", "c2", "des2", ["t2", "t3"])
        for metadata in ut_cases[0:2]:
            self._init_metadata(metadata, suite_metadata1)
        self._init_metadata(ut_cases[2], suite_metadata2)
        return ut_cases

    def _init_metadata(
        self, metadata: TestCaseMetadata, suite_metadata: TestSuiteMetadata
    ) -> None:
        func = _mock_test_function
        func.__name__ = f"mock_{metadata.description}"
        func.__qualname__ = f"mockclass.mock_{metadata.description}"
        metadata(func)
        metadata.set_suite(suite_metadata)
        suite_metadata.cases.append(metadata)


def _mock_test_function() -> None:
    pass
