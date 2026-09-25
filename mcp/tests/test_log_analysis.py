# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for log analysis tools."""

import unittest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestAnalyzeLog(unittest.TestCase):
    """Validate log parsing extracts correct results."""

    def test_extract_passed_results(self) -> None:
        from lisa_mcp.tools.log_analysis import _extract_test_results

        log = (
            "smoke_test | PASSED | completed in 42s\n"
            "verify_sriov | FAILED | assertion error\n"
            "verify_gpu | SKIPPED | no GPU found\n"
        )
        results = _extract_test_results(log)
        statuses = {r["name"]: r["status"] for r in results}
        self.assertEqual(statuses.get("smoke_test"), "PASSED")
        self.assertEqual(statuses.get("verify_sriov"), "FAILED")
        self.assertEqual(statuses.get("verify_gpu"), "SKIPPED")

    def test_extract_dotted_test_names(self) -> None:
        """Qualified names used to be truncated by a bare `\\w+` capture."""
        from lisa_mcp.tools.log_analysis import _extract_test_results

        log = (
            "storage.StorageTest.verify_disk | FAILED | mount error\n"
            "[PASSED] core.provisioning.smoke_test : ok\n"
        )
        statuses = {r["name"]: r["status"] for r in _extract_test_results(log)}
        self.assertEqual(statuses.get("storage.StorageTest.verify_disk"), "FAILED")
        self.assertEqual(statuses.get("core.provisioning.smoke_test"), "PASSED")

    def test_message_is_captured_for_every_pattern(self) -> None:
        """Named groups keep name/status/message straight across patterns."""
        from lisa_mcp.tools.log_analysis import _extract_test_results

        by_name = {
            r["name"]: r
            for r in _extract_test_results(
                "alpha | FAILED | pipe form\n[FAILED] beta : bracket form\n"
            )
        }
        self.assertEqual(by_name["alpha"]["message"], "pipe form")
        self.assertEqual(by_name["beta"]["status"], "FAILED")
        self.assertEqual(by_name["beta"]["message"], "bracket form")

    def test_extract_errors(self) -> None:
        from lisa_mcp.tools.log_analysis import _extract_errors

        log = (
            "2024-01-01 INFO starting test\n"
            "2024-01-01 ERROR failed to connect\n"
            "2024-01-01 DEBUG details\n"
            "2024-01-01 ERROR timeout occurred\n"
        )
        errors = _extract_errors(log)
        self.assertEqual(len(errors), 2)

    def test_extract_kernel_panics(self) -> None:
        from lisa_mcp.tools.log_analysis import _extract_kernel_panics

        log = (
            "[ 1.234] Kernel panic - not syncing: VFS: Unable to mount\n"
            "[ 2.345] BUG: soft lockup - CPU#0 stuck for 22s\n"
            "[ 3.456] Normal operation\n"
        )
        panics = _extract_kernel_panics(log)
        self.assertGreaterEqual(len(panics), 2)


class TestExplainFailure(unittest.TestCase):
    """Validate failure classification.

    These call the production classifier. An inline copy in this file would
    only prove the copy matches itself.
    """

    def test_classifies_kernel_panic(self) -> None:
        from lisa_mcp.tools.log_analysis import _classify_failure

        text = "Kernel panic - not syncing: VFS: Unable to mount root fs"
        self.assertIn("kernel", _classify_failure(text).lower())

    def test_classifies_connectivity(self) -> None:
        from lisa_mcp.tools.log_analysis import _classify_failure

        text = "TcpConnectionException: failed to connect to 10.0.0.5:22"
        self.assertIn("connect", _classify_failure(text).lower())

    def test_classifies_assertion(self) -> None:
        from lisa_mcp.tools.log_analysis import _classify_failure

        text = "AssertionError: assert_that(0).is_equal_to(1)"
        self.assertIn("assert", _classify_failure(text).lower())

    def test_classifies_timeout(self) -> None:
        from lisa_mcp.tools.log_analysis import _classify_failure

        text = "Operation timed out after 300 seconds"
        self.assertIn("timeout", _classify_failure(text).lower())

    def test_unclassified_text_is_reported(self) -> None:
        from lisa_mcp.tools.log_analysis import _classify_failure

        self.assertIn("unclassified", _classify_failure("all good").lower())


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
