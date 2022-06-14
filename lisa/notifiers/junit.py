# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import xml.etree.ElementTree as ET  # noqa: N817
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Dict, List, Type, Union, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.messages import (
    MessageBase,
    TestResultMessage,
    TestRunMessage,
    TestRunStatus,
    TestStatus,
)
from lisa.notifier import Notifier
from lisa.util import constants


@dataclass_json()
@dataclass
class JUnitSchema(schema.Notifier):
    path: str = "lisa.junit.xml"


class _TestSuiteInfo:
    def __init__(self) -> None:
        self.xml: ET.Element
        self.test_count: int = 0
        self.failed_count: int = 0


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
        self._xml_tree: ET.ElementTree

    # Test runner is initializing.
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook: JUnitSchema = cast(JUnitSchema, self.runbook)

        self._report_path = constants.RUN_LOCAL_LOG_PATH / runbook.path

        # Open file now, to avoid errors occuring after all the tests have completed.
        self._report_file = open(self._report_path, "wb")

        self._testsuites = ET.Element("testsuites")
        self._xml_tree = ET.ElementTree(self._testsuites)

        self._testsuites_info = {}

    # Test runner is closing.
    def finalize(self) -> None:
        try:
            self._xml_tree.write(self._report_file, xml_declaration=True)

        finally:
            self._report_file.close()

        self._log.info(f"JUnit: {self._report_path}")

    # The types of messages that this class supports.
    def _subscribed_message_type(self) -> List[Type[MessageBase]]:
        return [TestResultMessage, TestRunMessage]

    # Handle a message.
    def _received_message(self, message: MessageBase) -> None:
        if isinstance(message, TestRunMessage):
            self._received_test_run(message)

        elif isinstance(message, TestResultMessage):
            self._received_test_result(message)

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
        if message.status == TestStatus.RUNNING:
            self._test_case_running(message)

        elif message.is_completed:
            self._test_case_completed(message)

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

        self._testsuites.attrib["time"] = self._get_elapsed_str(message)
        self._testsuites.attrib["tests"] = str(total_tests)
        self._testsuites.attrib["failures"] = str(total_failures)
        self._testsuites.attrib["errors"] = "0"

    def _test_case_running(self, message: TestResultMessage) -> None:
        if message.suite_full_name not in self._testsuites_info:
            # Add test suite.
            testsuite_info = _TestSuiteInfo()

            testsuite_info.xml = ET.SubElement(self._testsuites, "testsuite")
            testsuite_info.xml.attrib["name"] = message.suite_full_name

            # Timestamp must not contain timezone information.
            timestamp = message.time.replace(tzinfo=None).isoformat(timespec="seconds")
            testsuite_info.xml.attrib["timestamp"] = timestamp

            self._testsuites_info[message.suite_full_name] = testsuite_info

    # Test case completed message.
    def _test_case_completed(self, message: TestResultMessage) -> None:
        testsuite_info = self._testsuites_info.get(message.suite_full_name)
        if not testsuite_info:
            return

        testcase = ET.SubElement(testsuite_info.xml, "testcase")
        testcase.attrib["name"] = message.name
        testcase.attrib["classname"] = message.suite_full_name
        testcase.attrib["time"] = self._get_elapsed_str(message)

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

    def _get_elapsed_str(
        self, message: Union[TestResultMessage, TestRunMessage]
    ) -> str:
        return f"{message.elapsed:.3f}"
