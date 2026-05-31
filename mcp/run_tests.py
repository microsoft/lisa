#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""LISA MCP Server — test runner.

Usage (from the mcp/ directory):
    python run_tests.py              # run all tests
    python run_tests.py --unit       # unit + functional tests only (fast)
    python run_tests.py --integration # MCP protocol integration tests only
    python run_tests.py --smoke      # quick smoke test (tool registration only)
    python run_tests.py --xml        # output JUnit XML to test-results.xml

Exit codes:
    0 — all tests passed
    1 — one or more tests failed
"""

import argparse
import os
import sys
import unittest
from pathlib import Path

# Ensure mcp/ is on sys.path
MCP_DIR = Path(__file__).resolve().parent
os.chdir(MCP_DIR)
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))


def _build_suite(mode: str) -> unittest.TestSuite:
    """Build a test suite based on the selected mode."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    if mode in ("all", "unit"):
        # Original unit tests
        suite.addTests(loader.loadTestsFromName("tests.test_authoring"))
        suite.addTests(loader.loadTestsFromName("tests.test_log_analysis"))
        # Comprehensive functional tests
        suite.addTests(loader.loadTestsFromName("tests.test_all_tools"))

    if mode in ("all", "integration"):
        suite.addTests(loader.loadTestsFromName("tests.test_mcp_integration"))

    if mode == "smoke":
        suite.addTests(
            loader.loadTestsFromName("tests.test_all_tools.TestToolRegistration")
        )

    return suite


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LISA MCP Server test runner",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--unit",
        action="store_true",
        help="Run unit and functional tests only (fast, no subprocess)",
    )
    group.add_argument(
        "--integration",
        action="store_true",
        help="Run MCP protocol integration tests only (starts server subprocess)",
    )
    group.add_argument(
        "--smoke",
        action="store_true",
        help="Quick smoke test — verify all 24 tools are registered",
    )
    parser.add_argument(
        "--xml",
        action="store_true",
        help="Output JUnit XML report to test-results.xml",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=True,
        help="Verbose output (default: True)",
    )
    args = parser.parse_args()

    if args.unit:
        mode = "unit"
    elif args.integration:
        mode = "integration"
    elif args.smoke:
        mode = "smoke"
    else:
        mode = "all"

    suite = _build_suite(mode)

    if args.xml:
        try:
            import xmlrunner  # type: ignore[import-untyped]

            runner = xmlrunner.XMLTestRunner(
                output="test-results",
                verbosity=2 if args.verbose else 1,
            )
        except ImportError:
            print(
                "WARNING: xmlrunner not installed. "
                "Install with: pip install unittest-xml-reporting\n"
                "Falling back to text output.\n",
                file=sys.stderr,
            )
            runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    else:
        runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)

    print(f"{'=' * 60}")
    print(f"LISA MCP Server Tests — mode: {mode}")
    print(f"{'=' * 60}\n")

    result = runner.run(suite)

    print(f"\n{'=' * 60}")
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - skipped
    print(
        f"Results: {passed} passed, {failed} failed, {skipped} skipped / {total} total"
    )
    print(f"{'=' * 60}")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
