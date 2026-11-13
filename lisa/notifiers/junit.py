# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import xml.etree.ElementTree as ET  # noqa: N817
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.messages import (
    MessageBase,
    SubTestMessage,
    TestResultMessage,
    TestResultMessageBase,
    TestRunMessage,
    TestRunStatus,
    TestStatus,
)
from lisa.notifier import Notifier
from lisa.util import LisaException, constants


@dataclass_json()
@dataclass
class JUnitSchema(schema.Notifier):
    path: str = "lisa.junit.xml"
    # respect the original behavior, include subtest by default
    include_subtest: bool = True
    # control whether to append message ID to test case names
    # useful when combinators are used to distinguish multiple test runs
    append_message_id: bool = True


class _TestSuiteInfo:
    def __init__(self) -> None:
        self.xml: ET.Element
        self.test_count: int = 0
        self.failed_count: int = 0


class _TestCaseInfo:
    def __init__(self) -> None:
        self.suite_full_name: str = ""
        self.name: str = ""
        self.active_subtest_name: Optional[str] = None
        self.last_seen_timestamp: float = 0.0
        self.subtest_total_elapsed: float = 0.0
        self.results: List[ET.Element] = []
        self.previous_attempt: Optional["_TestCaseInfo"] = None
        self.attempt_history: List[str] = []
        self.completed: bool = False
        self.pending_result: Optional[ET.Element] = None


# Outputs tests results in JUnit format.
# See, https://llg.cubic.org/docs/junit/
class JUnit(Notifier):
    @classmethod
    def type_name(cls) -> str:
        return "junit"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return JUnitSchema

    def __init__(self, runbook: schema.TypedSchema) -> None:
        super().__init__(runbook=runbook)

        self._report_path: Path
        self._testsuites: ET.Element
        self._testsuites_info: Dict[str, _TestSuiteInfo]
        self._testcases_info: Dict[str, _TestCaseInfo]
        self._xml_tree: ET.ElementTree

    # Test runner is initializing.
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook: JUnitSchema = cast(JUnitSchema, self.runbook)

        self._report_path = constants.RUN_LOCAL_LOG_PATH / runbook.path

        self._testsuites = ET.Element("testsuites")
        self._xml_tree = ET.ElementTree(self._testsuites)

        self._testsuites_info = {}
        self._testcases_info = {}
        self._write_results()

    # Test runner is closing.
    def finalize(self) -> None:
        self._write_results()
        self._log.info(f"JUnit: {self._report_path}")

    def _write_results(self) -> None:
        self._update_test_counts()
        temporary_path = self._report_path.with_name(f".{self._report_path.name}.tmp")
        try:
            with temporary_path.open("wb") as report_file:
                self._xml_tree.write(
                    report_file, xml_declaration=True, encoding="utf-8"
                )
            temporary_path.replace(self._report_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    # The types of messages that this class supports.
    def _subscribed_message_type(self) -> List[Type[MessageBase]]:
        subscribed_types = [TestResultMessage, TestRunMessage]

        runbook: JUnitSchema = cast(JUnitSchema, self.runbook)
        if runbook.include_subtest:
            subscribed_types.append(SubTestMessage)

        return subscribed_types

    # Handle a message.
    def _received_message(self, message: MessageBase) -> None:
        if isinstance(message, TestRunMessage):
            self._received_test_run(message)

        elif isinstance(message, TestResultMessage):
            self._received_test_result(message)

        elif isinstance(message, SubTestMessage):
            self._received_sub_test(message)

    # Handle a test run message.
    def _received_test_run(self, message: TestRunMessage) -> None:
        if message.status == TestRunStatus.INITIALIZING:
            self._test_run_started(message)

        elif (
            message.status == TestRunStatus.FAILED
            or message.status == TestRunStatus.SUCCESS
        ):
            self._test_run_completed(message)

    # Handle a test case message.
    def _received_test_result(self, message: TestResultMessage) -> None:
        if message.is_completed:
            self._test_case_completed(message)
        else:
            self._test_case_running(message)

    # Handle a sub test case message.
    def _received_sub_test(self, message: SubTestMessage) -> None:
        if message.status == TestStatus.RUNNING:
            self._sub_test_case_running(message)

        elif message.is_completed:
            self._sub_test_case_completed(message)

    def _set_test_suite_info(self, message: TestResultMessage) -> None:
        # Check if the test suite for this test case has been seen yet.
        if message.suite_full_name not in self._testsuites_info:
            # Add test suite.
            testsuite_info = _TestSuiteInfo()

            testsuite_info.xml = ET.SubElement(self._testsuites, "testsuite")
            testsuite_info.xml.attrib["name"] = message.suite_full_name

            # Timestamp must not contain timezone information.
            assert message.time is not None, "Message time should not be None"
            timestamp = message.time.replace(tzinfo=None).isoformat(timespec="seconds")
            testsuite_info.xml.attrib["timestamp"] = timestamp

            self._testsuites_info[message.suite_full_name] = testsuite_info

    def _set_test_case_info(self, message: TestResultMessage) -> None:
        testcase_info = _TestCaseInfo()
        testcase_info.suite_full_name = message.suite_full_name
        testcase_info.name = message.name
        testcase_info.last_seen_timestamp = message.elapsed
        self._testcases_info[message.id_] = testcase_info

    # Test run started message.
    def _test_run_started(self, message: TestRunMessage) -> None:
        self._testsuites.attrib["name"] = message.runbook_name

    # Test run completed message.
    def _test_run_completed(self, message: TestRunMessage) -> None:
        self._testsuites.attrib["time"] = self._get_elapsed_str(message.elapsed)
        self._update_test_counts()

    def _update_test_counts(self) -> None:
        total_tests = 0
        total_failures = 0

        for testsuite_info in self._testsuites_info.values():
            testsuite_info.xml.attrib["tests"] = str(testsuite_info.test_count)
            testsuite_info.xml.attrib["failures"] = str(testsuite_info.failed_count)
            testsuite_info.xml.attrib["errors"] = "0"

            total_tests += testsuite_info.test_count
            total_failures += testsuite_info.failed_count

        self._testsuites.attrib["tests"] = str(total_tests)
        self._testsuites.attrib["failures"] = str(total_failures)
        self._testsuites.attrib["errors"] = "0"

    # Test case started message.
    def _test_case_running(self, message: TestResultMessage) -> None:
        self._set_test_suite_info(message)

        previous = self._testcases_info.get(message.id_)
        if previous is not None and not previous.completed:
            testcase_info = previous
        else:
            self._set_test_case_info(message)
            testcase_info = self._testcases_info[message.id_]
            if previous is not None:
                testcase_info.previous_attempt = previous
                snapshots = []
                for result in previous.results:
                    snapshot = deepcopy(result)
                    for history in snapshot.findall("system-out"):
                        snapshot.remove(history)
                    snapshots.append(ET.tostring(snapshot, encoding="unicode"))
                testcase_info.attempt_history = previous.attempt_history + [
                    f"Attempt {len(previous.attempt_history) + 1}:\n"
                    + "\n".join(snapshots)
                ]

        self._remove_pending_result(testcase_info)
        if message.status == TestStatus.RUNNING:
            testcase_info.subtest_total_elapsed = 0.0
            testcase_info.last_seen_timestamp = message.elapsed
            pending_message = replace(
                message,
                status=TestStatus.FAILED,
                message="Test execution was interrupted before a terminal result.",
            )
        else:
            pending_message = replace(
                message,
                status=TestStatus.SKIPPED,
                message="Test was selected but did not reach execution.",
            )
        testcase_info.pending_result = self._add_test_case_result(
            pending_message,
            message.suite_full_name,
            message.suite_full_name,
            message.elapsed,
        )
        self._write_results()

    def _remove_pending_result(self, testcase_info: _TestCaseInfo) -> None:
        pending_result = testcase_info.pending_result
        if pending_result is not None:
            testsuite_info = self._testsuites_info[testcase_info.suite_full_name]
            testsuite_info.xml.remove(pending_result)
            testsuite_info.test_count -= 1
            if pending_result.find("failure") is not None:
                testsuite_info.failed_count -= 1
            testcase_info.results.remove(pending_result)
            testcase_info.pending_result = None

    # Test case completed message.
    def _test_case_completed(self, message: TestResultMessage) -> None:
        self._set_test_suite_info(message)

        if (
            message.id_ not in self._testcases_info
            or self._testcases_info[message.id_].completed
        ):
            self._test_case_running(message)

        testcase_info = self._testcases_info[message.id_]

        # Check if there is an already active sub-test case that wasn't closed out.
        if testcase_info.active_subtest_name is not None:
            # Close out the sub-test case.
            # If the test case encountered any errors, assume they are associated with
            # the active sub-test case.
            completed_message = SubTestMessage()
            completed_message.id_ = message.id_
            completed_message.name = testcase_info.active_subtest_name
            completed_message.status = message.status
            completed_message.message = message.message
            completed_message.stacktrace = message.stacktrace
            completed_message.elapsed = message.elapsed

            self._sub_test_case_completed(completed_message)

        self._remove_pending_result(testcase_info)
        # Calculate total time spent in test case that was not spent in a sub-test case.
        elapsed = message.elapsed - testcase_info.subtest_total_elapsed

        # Keep earlier failures visible until a retry has a terminal outcome.
        previous = testcase_info.previous_attempt
        if previous is not None:
            suite = self._testsuites_info[previous.suite_full_name]
            for result in previous.results:
                suite.xml.remove(result)
                suite.test_count -= 1
                if result.find("failure") is not None:
                    suite.failed_count -= 1
            testcase_info.previous_attempt = None

        # Add test case result.
        self._add_test_case_result(
            message, message.suite_full_name, message.suite_full_name, elapsed
        )
        testcase_info.completed = True
        self._write_results()

    # Sub test case started message.
    def _sub_test_case_running(self, message: SubTestMessage) -> None:
        testcase_info = self._testcases_info[message.id_]

        # Check if there is an already active sub-test case that wasn't closed out.
        if testcase_info.active_subtest_name is not None:
            # Assume the previous sub-test case succeeded.
            completed_message = SubTestMessage()
            completed_message.id_ = message.id_
            completed_message.name = testcase_info.active_subtest_name
            completed_message.status = TestStatus.PASSED
            completed_message.elapsed = message.elapsed

            self._sub_test_case_completed(completed_message)

        # Mark the new sub-test case as running.
        testcase_info.active_subtest_name = message.name
        testcase_info.last_seen_timestamp = message.elapsed

    # Sub test case completed message.
    def _sub_test_case_completed(self, message: SubTestMessage) -> None:
        testcase_info = self._testcases_info[message.id_]

        # Check if there is an already active sub-test.
        if testcase_info.active_subtest_name is not None:
            if testcase_info.active_subtest_name != message.name:
                # The active sub-test is not the same as the one that just completed.
                # Report the problem.
                raise LisaException(
                    "Completed sub-test is not the same as the active sub-test."
                )

            testcase_info.active_subtest_name = None

        # Use subtest_duration if provided (actual timing from test tool),
        # otherwise calculate from elapsed timestamps (legacy behavior).
        if message.subtest_duration is not None:
            elapsed = message.subtest_duration
        else:
            elapsed = message.elapsed - testcase_info.last_seen_timestamp
        testcase_info.subtest_total_elapsed += elapsed

        # Add sub-test case result.
        self._add_test_case_result(
            message,
            testcase_info.suite_full_name,
            f"{testcase_info.suite_full_name}.{testcase_info.name}",
            elapsed,
        )
        self._write_results()

        testcase_info.last_seen_timestamp = message.elapsed

    # Add test case result to XML.
    def _add_test_case_result(
        self,
        message: TestResultMessageBase,
        suite_full_name: str,
        class_name: str,
        elapsed: float,
    ) -> ET.Element:
        testsuite_info = self._testsuites_info.get(suite_full_name)
        if not testsuite_info:
            raise LisaException("Test suite not started.")

        runbook: JUnitSchema = cast(JUnitSchema, self.runbook)

        testcase = ET.SubElement(testsuite_info.xml, "testcase")
        if runbook.append_message_id:
            testcase.attrib["name"] = f"{message.name} ({message.id_})"
        else:
            testcase.attrib["name"] = message.name
        testcase.attrib["classname"] = class_name
        testcase.attrib["time"] = self._get_elapsed_str(elapsed)

        if message.status == TestStatus.FAILED:
            failure = ET.SubElement(testcase, "failure")
            failure.attrib["message"] = message.message
            failure.text = message.stacktrace

            testsuite_info.failed_count += 1

        elif (
            message.status == TestStatus.SKIPPED
            or message.status == TestStatus.ATTEMPTED
            or message.status == TestStatus.EXPUNGED
        ):
            skipped = ET.SubElement(testcase, "skipped")
            skipped.attrib["message"] = message.message

        testcase_info = self._testcases_info[message.id_]
        testcase_info.results.append(testcase)
        if isinstance(message, TestResultMessage) and testcase_info.attempt_history:
            history = ET.SubElement(testcase, "system-out")
            history.text = "\n\n".join(testcase_info.attempt_history)

        testsuite_info.test_count += 1

        return testcase

    def _get_elapsed_str(self, elapsed: float) -> str:
        return f"{elapsed:.3f}"
