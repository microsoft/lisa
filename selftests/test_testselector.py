# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List
from unittest import TestCase

from lisa import LisaException, constants
from lisa.testselector import select_testcases
from lisa.testsuite import TestCaseMetadata, TestSuiteMetadata
from selftests.test_testsuite import (
    cleanup_cases_metadata,
    generate_cases_metadata,
    select_and_check,
)


class SelectorTestCase(TestCase):
    def setUp(self) -> None:
        cleanup_cases_metadata()

    def test_no_case_selected(self) -> None:
        runbook = [{constants.TESTCASE_CRITERIA: {"area": "demo"}}]
        select_and_check(self, runbook, [])

    def test_select_by_priority(self) -> None:
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


class MaturitySelectorTestCase(TestCase):
    """Tests for the test maturity model (stable gate)."""

    def setUp(self) -> None:
        cleanup_cases_metadata()

    def _generate_maturity_cases(self) -> List[TestCaseMetadata]:
        """Generate cases: ut1=stable, ut2=preview, ut3=experimental."""
        cases = generate_cases_metadata()
        # ut1 stays stable (default)
        cases[1]._maturity = constants.TESTCASE_MATURITY_PREVIEW
        cases[2]._maturity = constants.TESTCASE_MATURITY_EXPERIMENTAL
        return cases

    def test_no_filter_only_stable_selected(self) -> None:
        """Without filters, only stable tests are selected."""
        cases = self._generate_maturity_cases()
        selected = select_testcases(filters=None, init_cases=cases)
        self.assertListEqual(["ut1"], [c.description for c in selected])

    def test_no_filter_all_stable_backward_compat(self) -> None:
        """Without filters, all-stable cases return everything (backward compat)."""
        cases = generate_cases_metadata()
        selected = select_testcases(filters=None, init_cases=cases)
        self.assertListEqual(["ut1", "ut2", "ut3"], [c.description for c in selected])

    def test_include_all_stable_gate_drops_non_stable(self) -> None:
        """Include-all filter without maturity criterion: stable gate drops
        non-stable tests."""
        cases = self._generate_maturity_cases()
        runbook = [{constants.TESTCASE_CRITERIA: {"priority": [0, 1, 2]}}]
        select_and_check(self, runbook, ["ut1"], init_cases=cases)

    def test_include_with_maturity_preview(self) -> None:
        """Including maturity: [preview] approves preview tests through the
        stable gate while stable tests included by other criteria still pass."""
        cases = self._generate_maturity_cases()
        runbook = [
            {constants.TESTCASE_CRITERIA: {"priority": [0, 1, 2]}},
            {constants.TESTCASE_CRITERIA: {"maturity": "preview"}},
        ]
        select_and_check(self, runbook, ["ut1", "ut2"], init_cases=cases)

    def test_include_with_maturity_list(self) -> None:
        """Including maturity: [preview, experimental] approves both levels."""
        cases = self._generate_maturity_cases()
        runbook = [
            {constants.TESTCASE_CRITERIA: {"priority": [0, 1, 2]}},
            {constants.TESTCASE_CRITERIA: {"maturity": ["preview", "experimental"]}},
        ]
        select_and_check(self, runbook, ["ut1", "ut2", "ut3"], init_cases=cases)

    def test_maturity_criterion_only(self) -> None:
        """Including only maturity: [preview] selects only preview tests."""
        cases = self._generate_maturity_cases()
        runbook = [{constants.TESTCASE_CRITERIA: {"maturity": "preview"}}]
        select_and_check(self, runbook, ["ut2"], init_cases=cases)

    def test_force_include_overrides_stable_gate(self) -> None:
        """forceInclude overrides the stable gate for non-stable tests."""
        cases = self._generate_maturity_cases()
        runbook = [
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut3"},
                constants.TESTCASE_SELECT_ACTION: "forceInclude",
            },
        ]
        select_and_check(self, runbook, ["ut3"], init_cases=cases)

    def test_force_exclude_overrides_stable(self) -> None:
        """forceExclude removes even stable tests."""
        cases = self._generate_maturity_cases()
        runbook = [
            {constants.TESTCASE_CRITERIA: {"priority": [0, 1, 2]}},
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut1"},
                constants.TESTCASE_SELECT_ACTION: "forceExclude",
            },
        ]
        select_and_check(self, runbook, [], init_cases=cases)

    def test_deprecated_excluded_by_default(self) -> None:
        """Deprecated tests are excluded by the stable gate."""
        cases = generate_cases_metadata()
        cases[1]._maturity = constants.TESTCASE_MATURITY_DEPRECATED
        runbook = [{constants.TESTCASE_CRITERIA: {"priority": [0, 1, 2]}}]
        select_and_check(self, runbook, ["ut1", "ut3"], init_cases=cases)

    def test_deprecated_force_include(self) -> None:
        """Deprecated tests can be force-included (escape hatch)."""
        cases = generate_cases_metadata()
        cases[1]._maturity = constants.TESTCASE_MATURITY_DEPRECATED
        runbook = [
            {
                constants.TESTCASE_CRITERIA: {"name": "mock_ut2"},
                constants.TESTCASE_SELECT_ACTION: "forceInclude",
            },
        ]
        select_and_check(self, runbook, ["ut2"], init_cases=cases)

    def test_suite_maturity_inherited(self) -> None:
        """Case without explicit maturity inherits suite maturity."""
        cases = generate_cases_metadata()
        # set suite-level maturity to preview
        cases[0].suite.maturity = constants.TESTCASE_MATURITY_PREVIEW
        # ut1 and ut2 are in suite1 (now preview), ut3 in suite2 (stable)
        runbook = [{constants.TESTCASE_CRITERIA: {"priority": [0, 1, 2]}}]
        select_and_check(self, runbook, ["ut3"], init_cases=cases)

    def test_case_maturity_overrides_suite(self) -> None:
        """Case-level maturity overrides suite-level maturity."""
        cases = generate_cases_metadata()
        # set suite-level maturity to preview (non-stable)
        cases[0].suite.maturity = constants.TESTCASE_MATURITY_PREVIEW
        # but override ut1 back to stable at case level
        cases[0]._maturity = constants.TESTCASE_MATURITY_STABLE
        runbook = [{constants.TESTCASE_CRITERIA: {"priority": [0, 1, 2]}}]
        select_and_check(self, runbook, ["ut1", "ut3"], init_cases=cases)

    def test_invalid_maturity_on_case_raises(self) -> None:
        """Invalid maturity value on TestCaseMetadata raises LisaException."""
        with self.assertRaises(LisaException) as cm:
            TestCaseMetadata("bad", maturity="basic")
        self.assertIn("basic", str(cm.exception))

    def test_invalid_maturity_on_suite_raises(self) -> None:
        """Invalid maturity value on TestSuiteMetadata raises LisaException."""
        with self.assertRaises(LisaException) as cm:
            TestSuiteMetadata("a", "c", "d", maturity="unknown")
        self.assertIn("unknown", str(cm.exception))
