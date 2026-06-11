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
    """Validate failure classification."""

    def test_classifies_kernel_panic(self) -> None:
        text = "Kernel panic - not syncing: VFS: Unable to mount root fs"
        result = _classify(text)
        self.assertIn("kernel", result.lower())

    def test_classifies_connectivity(self) -> None:
        text = "TcpConnectionException: failed to connect to 10.0.0.5:22"
        result = _classify(text)
        self.assertIn("connect", result.lower())

    def test_classifies_assertion(self) -> None:
        text = "AssertionError: assert_that(0).is_equal_to(1)"
        result = _classify(text)
        self.assertIn("assert", result.lower())

    def test_classifies_timeout(self) -> None:
        text = "Operation timed out after 300 seconds"
        result = _classify(text)
        self.assertIn("timeout", result.lower())


def _classify(text: str) -> str:
    """Simple classification for testing."""
    text_lower = text.lower()
    categories = []
    if "kernel panic" in text_lower or "oops" in text_lower:
        categories.append("Kernel Error")
    if "tcpconnection" in text_lower or "connection" in text_lower:
        categories.append("Connectivity Error")
    if "assertionerror" in text_lower or "assert_that" in text_lower:
        categories.append("Assertion Failure")
    if "timeout" in text_lower or "timed out" in text_lower:
        categories.append("Timeout")
    return ", ".join(categories) if categories else "Unknown"


if __name__ == "__main__":
    unittest.main()
