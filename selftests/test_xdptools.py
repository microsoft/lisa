# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime, timezone
from pathlib import Path, PurePath
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from xml.etree import ElementTree

from lisa.messages import SubTestMessage, TestResultMessage, TestStatus
from lisa.microsoft.testsuites.xdp.xdptools import XdpTool
from lisa.notifiers.junit import JUnit, JUnitSchema
from lisa.testsuite import TestResult
from lisa.util import LisaException, constants
from lisa.util.process import ExecutableResult


class XdpToolTestCase(TestCase):
    def setUp(self) -> None:
        self.tool = XdpTool.__new__(XdpTool)
        self.node = Mock()
        self.tool.node = self.node
        self.tool._code_path = PurePath("/mock/xdp-tools")
        self.parent = Mock(spec=TestResult)
        self.parent.id_ = "xdp_1"
        self.parent.environment_information = {"platform": "mock"}
        self.parent.runtime_data = Mock()
        self.parent.runtime_data.name = "verify_xdp_community_test"
        self.parent.get_elapsed.return_value = 1.0

    def _set_output(self, stdout: str, exit_code: int = 0) -> None:
        self.node.execute.return_value = ExecutableResult(
            stdout, "", exit_code, "make test", "mock", 1.0
        )

    def test_reports_all_results_before_raising(self) -> None:
        self._set_output(
            " [test_xsk_prog_refcnt_bpffs] FAIL\n"
            " [test_pass] PASS\n"
            " [test_skip] SKIPPED\n"
            " [test_xsk_prog_refcnt_legacy] FAIL\n",
            exit_code=1,
        )
        with patch("lisa.messages.notifier.notify") as notify:
            with self.assertRaisesRegex(LisaException, "found failed tests:"):
                self.tool.run_full_test(self.parent)
        messages = [call.args[0] for call in notify.call_args_list]
        self.assertEqual(
            [(message.name, message.status) for message in messages],
            [
                ("test_xsk_prog_refcnt_bpffs", TestStatus.FAILED),
                ("test_pass", TestStatus.PASSED),
                ("test_skip", TestStatus.SKIPPED),
                ("test_xsk_prog_refcnt_legacy", TestStatus.FAILED),
            ],
        )
        for message in messages:
            self.assertIsInstance(message, SubTestMessage)
            self.assertEqual(message.id_, self.parent.id_)
            self.assertEqual(message.parent_test, self.parent.runtime_data.name)

    def test_passed_and_skipped_results_do_not_fail_parent(self) -> None:
        self._set_output(" [test_pass] PASS\n [test_skip] SKIPPED\n")
        with patch("lisa.messages.notifier.notify") as notify:
            self.tool.run_full_test(self.parent)
        self.assertEqual(notify.call_count, 2)

    def test_unknown_status_remains_a_failure(self) -> None:
        self._set_output(" [test_unknown] ERROR\n")
        with patch("lisa.messages.notifier.notify") as notify:
            with self.assertRaisesRegex(LisaException, "'test_unknown': 'ERROR'"):
                self.tool.run_full_test(self.parent)
        message = notify.call_args.args[0]
        self.assertEqual(message.status, TestStatus.FAILED)
        self.assertEqual(message.message, "ERROR")

    def test_execution_error_has_no_fabricated_failed_subtests(self) -> None:
        for output in ("make: build failed\n", " [test_pass] PASS\n"):
            with self.subTest(output=output):
                self._set_output(output, exit_code=1)
                with patch("lisa.messages.notifier.notify") as notify:
                    with self.assertRaises(AssertionError):
                        self.tool.run_full_test(self.parent)
                self.assertFalse(
                    any(
                        call.args[0].status == TestStatus.FAILED
                        for call in notify.call_args_list
                    )
                )

    def test_junit_links_failed_children_to_parent(self) -> None:
        self._set_output(
            " [test_xsk_prog_refcnt_bpffs] FAIL\n"
            " [test_xsk_prog_refcnt_legacy] FAIL\n",
            exit_code=1,
        )
        with TemporaryDirectory() as directory:
            report_path = Path(directory) / "lisa.junit.xml"
            with patch.object(constants, "RUN_LOCAL_LOG_PATH", Path(directory)):
                junit = JUnit(JUnitSchema(type="junit", include_subtest=True))
                junit._initialize()
            try:
                junit._received_message(
                    TestResultMessage(
                        id_=self.parent.id_,
                        name=self.parent.runtime_data.name,
                        suite_full_name="XdpFunctional",
                        status=TestStatus.RUNNING,
                        time=datetime.now(timezone.utc),
                    )
                )
                with patch(
                    "lisa.messages.notifier.notify", side_effect=junit._received_message
                ):
                    with self.assertRaises(LisaException) as failure:
                        self.tool.run_full_test(self.parent)
                junit._received_message(
                    TestResultMessage(
                        id_=self.parent.id_,
                        name=self.parent.runtime_data.name,
                        suite_full_name="XdpFunctional",
                        status=TestStatus.FAILED,
                        message=str(failure.exception),
                        elapsed=1.0,
                    )
                )
            finally:
                junit.finalize()

            cases = ElementTree.parse(report_path).findall(".//testcase")
            self.assertEqual(len(cases), 3)
            self.assertEqual(
                [(case.get("name"), case.get("classname")) for case in cases],
                [
                    (
                        "test_xsk_prog_refcnt_bpffs (xdp_1)",
                        "XdpFunctional.verify_xdp_community_test",
                    ),
                    (
                        "test_xsk_prog_refcnt_legacy (xdp_1)",
                        "XdpFunctional.verify_xdp_community_test",
                    ),
                    ("verify_xdp_community_test (xdp_1)", "XdpFunctional"),
                ],
            )
            for case in cases:
                self.assertIsNotNone(case.find("failure"))
