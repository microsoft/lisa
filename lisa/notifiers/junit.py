# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import xml.etree.ElementTree as ET  # noqa: N817
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Dict, List, Optional, Type, cast

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
        self._report_file: IO[Any]
        self._testsuites: ET.Element
        self._testsuites_info: Dict[str, _TestSuiteInfo]
        self._testcases_info: Dict[str, _TestCaseInfo]
        self._xml_tree: ET.ElementTree

    # Test runner is initializing.
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook: JUnitSchema = cast(JUnitSchema, self.runbook)

        self._report_path = constants.RUN_LOCAL_LOG_PATH / runbook.path

        # Open file now, to avoid errors occurring after all the tests have completed.
        self._report_file = open(self._report_path, "wb")

        self._testsuites = ET.Element("testsuites")
        self._xml_tree = ET.ElementTree(self._testsuites)

        self._testsuites_info = {}
        self._testcases_info = {}

    # Test runner is closing.
    def finalize(self) -> None:
        try:
            self._write_results()

        finally:
            self._report_file.close()

        self._log.info(f"JUnit: {self._report_path}")

    def _write_results(self) -> None:
        self._report_file.truncate(0)
        self._report_file.seek(0)
        self._xml_tree.write(self._report_file, xml_declaration=True, encoding="utf-8")
        self._report_file.flush()

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
        if message.status in [TestStatus.RUNNING, TestStatus.SKIPPED]:
            self._test_case_running(message)

        if message.is_completed:
            self._test_case_completed(message)

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

            # Write out current results to file.
            self._write_results()

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
        total_tests = 0
        total_failures = 0

        for testsuite_info in self._testsuites_info.values():
            testsuite_info.xml.attrib["tests"] = str(testsuite_info.test_count)
            testsuite_info.xml.attrib["failures"] = str(testsuite_info.failed_count)
            testsuite_info.xml.attrib["errors"] = "0"

            total_tests += testsuite_info.test_count
            total_failures += testsuite_info.failed_count

        self._testsuites.attrib["time"] = self._get_elapsed_str(message.elapsed)
        self._testsuites.attrib["tests"] = str(total_tests)
        self._testsuites.attrib["failures"] = str(total_failures)
        self._testsuites.attrib["errors"] = "0"

    # Test case started message.
    def _test_case_running(self, message: TestResultMessage) -> None:
        self._set_test_suite_info(message)

        # Initialize test-case info.
        self._set_test_case_info(message)

    # Test case completed message.
    def _test_case_completed(self, message: TestResultMessage) -> None:
        self._set_test_suite_info(message)

        # check if the message id is in the testcases_info dictionary
        # if not, then it is a test case  was attached to a failed environment
        # and we should add it to the results
        if message.id_ not in self._testcases_info.keys():
            self._set_test_case_info(message)

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

        # Calculate total time spent in test case that was not spent in a sub-test case.
        elapsed = message.elapsed - testcase_info.subtest_total_elapsed

        # Add test case result.
        self._add_test_case_result(
            message, message.suite_full_name, message.suite_full_name, elapsed
        )

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

        # Calculate the amount of time spent in the sub-test case.
        elapsed = message.elapsed - testcase_info.last_seen_timestamp
        testcase_info.subtest_total_elapsed += elapsed

        # Add sub-test case result.
        self._add_test_case_result(
            message,
            testcase_info.suite_full_name,
            f"{testcase_info.suite_full_name}.{testcase_info.name}",
            elapsed,
        )

        testcase_info.last_seen_timestamp = message.elapsed

    # Add test case result to XML.
    def _add_test_case_result(
        self,
        message: TestResultMessageBase,
        suite_full_name: str,
        class_name: str,
        elapsed: float,
    ) -> None:
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
        ):
            skipped = ET.SubElement(testcase, "skipped")
            skipped.attrib["message"] = message.message

        testsuite_info.test_count += 1

        # Write out current results to file.
        self._write_results()

    def _get_elapsed_str(self, elapsed: float) -> str:
        return f"{elapsed:.3f}"
