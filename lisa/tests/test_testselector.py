from unittest import TestCase

from lisa.tests.test_testsuite import cleanup_cases_metadata, select_and_check
from lisa.util import LisaException, constants


class SelectorTestCase(TestCase):
    def setUp(self) -> None:
        cleanup_cases_metadata()

    def test_no_case_selected(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"area": "demo"}}]
        select_and_check(self, runbook, [])

    def test_skip_not_enabled(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tags": "t2"}, constants.ENABLE: False},
            {constants.TESTCASE_CRITERIA: {"tags": "t3"}},
        ]
        select_and_check(self, runbook, ["ut3"])

    def test_select_by_priroity(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"priority": 0}}]
        select_and_check(self, runbook, ["ut1"])

    def test_select_by_tag(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"tags": "t1"}}]
        select_and_check(self, runbook, ["ut1", "ut2"])

    def test_select_by_one_of_tag(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"tags": ["t1", "t3"]}}]
        select_and_check(self, runbook, ["ut1", "ut2", "ut3"])

    def test_select_by_two_rules(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"tags": ["t1", "t3"], "area": "a1"}}]
        select_and_check(self, runbook, ["ut1", "ut2"])

    def test_select_by_two_criteria(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"name": "mock_ut1"}},
            {constants.TESTCASE_CRITERIA: {"name": "mock_ut2"}},
        ]
        select_and_check(self, runbook, ["ut1", "ut2"])

    def test_select_then_drop(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tags": "t1"}},
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "exclude",
            },
        ]
        select_and_check(self, runbook, ["ut1"])

    def test_select_drop_select(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tags": "t1"}},
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "exclude",
            },
            {constants.TESTCASE_CRITERIA: {"tags": "t1"}},
        ]
        select_and_check(self, runbook, ["ut1", "ut2"])

    def test_select_force_include(self) -> None:
        runbook = [
            {
                constants.TESTCASE_CRITERIA: {"tags": "t1"},
                constants.TESTCASE_SELECT_ACTION: "forceInclude",
            },
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "exclude",
            },
        ]
        select_and_check(self, runbook, ["ut1", "ut2"])

    def test_select_force_conflict(self) -> None:
        runbook = [
            {
                constants.TESTCASE_CRITERIA: {"tags": "t1"},
                constants.TESTCASE_SELECT_ACTION: "forceInclude",
            },
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "forceExclude",
            },
        ]
        with self.assertRaises(LisaException) as cm:
            select_and_check(self, runbook, ["ut1", "ut2"])
        self.assertIsInstance(cm.exception, LisaException)
        self.assertIn("force", str(cm.exception))

    def test_select_force_conflict_exclude(self) -> None:
        runbook = [
            {
                constants.TESTCASE_CRITERIA: {"tags": "t1"},
                constants.TESTCASE_SELECT_ACTION: "include",
            },
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "forceExclude",
            },
            {
                constants.TESTCASE_CRITERIA: {"tags": "t1"},
                constants.TESTCASE_SELECT_ACTION: "forceInclude",
            },
        ]
        with self.assertRaises(LisaException) as cm:
            select_and_check(self, runbook, [])
            self.assertIsInstance(cm.exception, LisaException)
            self.assertIn("force", str(cm.exception))

    def test_select_with_setting(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tags": "t1"}, "retry": 2},
        ]
        selected = select_and_check(self, runbook, ["ut1", "ut2"])

        self.assertListEqual([2, 2], [case.retry for case in selected])

    def test_select_with_times(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tags": "t1"}},
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                "times": 2,
                constants.TESTCASE_SELECT_ACTION: "none",
            },
        ]
        selected = select_and_check(self, runbook, ["ut1", "ut2", "ut2"])

        self.assertListEqual([1, 2, 2], [case.times for case in selected])
        self.assertListEqual([0, 0, 0], [case.retry for case in selected])

    def test_select_with_setting_none(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tags": "t1"}},
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                "retry": 2,
                constants.TESTCASE_SELECT_ACTION: "none",
            },
        ]
        selected = select_and_check(self, runbook, ["ut1", "ut2"])
        self.assertListEqual([0, 2], [case.retry for case in selected])

    def test_select_with_diff_setting(self) -> None:
        runbook = [
            {constants.TESTCASE_CRITERIA: {"tags": "t1"}, "retry": 2},
            {constants.TESTCASE_CRITERIA: {"name": "mock_ut2"}, "retry": 3},
        ]
        selected = select_and_check(self, runbook, ["ut1", "ut2"])

        self.assertListEqual([2, 3], [case.retry for case in selected])
