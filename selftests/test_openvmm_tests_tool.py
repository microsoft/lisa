# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from lisa.microsoft.testsuites.openvmm.openvmm_tests_tool import OpenVmmTests
from lisa.util import LisaException


class OpenVmmTestsToolTestCase(TestCase):
    def test_check_vmm_tests_results_raises_on_junit_failures(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "openvmm_vmm_tests.log"
            junit_file = temp_path / "openvmm_vmm_tests.junit.xml"
            log_file.write_text("", encoding="utf-8")
            junit_file.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="x64-linux-vmm-tests" tests="17" failures="7" errors="0" skipped="41">
    <testcase
      classname="vmm_tests::tests"
      name="multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic">
      <failure message="failed">stack</failure>
    </testcase>
  </testsuite>
</testsuites>
""",
                encoding="utf-8",
            )

            with self.assertRaises(LisaException) as context:
                tool._check_vmm_tests_results(
                    name="openvmm_vmm_tests",
                    log_file=log_file,
                    junit_file=junit_file,
                )

            self.assertIn(
                "17 tests run: 0 passed, 7 failed, 41 skipped",
                str(context.exception),
            )
            self.assertIn("Failed tests:", str(context.exception))
        self.assertIn(
            "multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic",
            str(context.exception),
        )

    def test_check_vmm_tests_results_raises_on_log_summary_without_junit(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "openvmm_vmm_tests.log"
            log_file.write_text(
                """
Summary [   0.071s] 7/17 tests run: 0 passed, 7 failed, 41 skipped
    FAIL [   0.069s] vmm_tests::tests
          multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic
warning: 10/17 tests were not run due to test failure
error: test run failed
encountered at least one test failure!
encountered test failures.
""",
                encoding="utf-8",
            )

            with self.assertRaises(LisaException) as context:
                tool._check_vmm_tests_results(
                    name="openvmm_vmm_tests",
                    log_file=log_file,
                    junit_file=temp_path / "missing.junit.xml",
                )

            self.assertIn(
                "7/17 tests run: 0 passed, 7 failed, 41 skipped",
                str(context.exception),
            )
        self.assertIn("7 failed", str(context.exception))

    def test_check_vmm_tests_results_deduplicates_failed_tests_and_reports_passes(
        self,
    ) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "openvmm_vmm_tests.log"
            log_file.write_text(
                """
Summary [ 600.338s] 3 tests run: 2 passed, 1 failed, 45 skipped
    PASS [ 120.000s] vmm_tests::tests
          multiarch::openvmm_uefi_x64_ubuntu_2404_server_x64_boot
    PASS [ 130.000s] vmm_tests::tests
          multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic
    FAIL [ 600.335s] vmm_tests::tests
          multiarch::openvmm_uefi_x64_alpine_3_23_x64_boot_small
    FAIL [ 600.335s] vmm_tests::tests
          multiarch::openvmm_uefi_x64_alpine_3_23_x64_boot_small
encountered at least one test failure!
""",
                encoding="utf-8",
            )

            with self.assertRaises(LisaException) as context:
                tool._check_vmm_tests_results(
                    name="openvmm_vmm_tests",
                    log_file=log_file,
                    junit_file=temp_path / "missing.junit.xml",
                )

        message = str(context.exception)
        self.assertIn("3 tests run: 2 passed, 1 failed, 45 skipped", message)
        self.assertIn("Passed tests:", message)
        self.assertIn("Failed tests:", message)
        failed_test_name = "multiarch::openvmm_uefi_x64_alpine_3_23_x64_boot_small"
        self.assertEqual(
            1,
            message.count(failed_test_name),
        )

    def test_check_vmm_tests_results_accepts_passing_junit(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "openvmm_vmm_tests.log"
            junit_file = temp_path / "openvmm_vmm_tests.junit.xml"
            log_file.write_text("", encoding="utf-8")
            junit_file.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="x64-linux-vmm-tests" tests="2" failures="0" errors="0" skipped="1">
    <testcase classname="vmm_tests::tests" name="multiarch::openvmm_boot" />
    <testcase classname="vmm_tests::tests" name="multiarch::openvmm_skip">
      <skipped message="filtered" />
    </testcase>
  </testsuite>
</testsuites>
""",
                encoding="utf-8",
            )

            summary = tool._check_vmm_tests_results(
                name="openvmm_vmm_tests",
                log_file=log_file,
                junit_file=junit_file,
            )

        self.assertEqual(2, summary.tests)
        self.assertEqual(1, summary.skipped)
        self.assertEqual(
            ["vmm_tests::tests multiarch::openvmm_boot"],
            summary.passed_tests,
        )
