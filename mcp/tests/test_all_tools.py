# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Comprehensive functional tests for all MCP tools.

Run from the mcp/ directory:
    python -m pytest tests/test_all_tools.py -v
    python -m unittest tests.test_all_tools -v

These tests invoke each tool directly (without MCP protocol overhead)
and verify correct behavior with realistic inputs.
"""

import ipaddress
import json
import keyword
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional
from unittest import mock

import yaml

# Ensure mcp/ is on sys.path so `tools.*` imports work
_MCP_DIR = Path(__file__).resolve().parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from server import mcp  # noqa: E402 — registers all tools

from lisa_mcp import runtime  # noqa: E402
from lisa_mcp.config import (  # noqa: E402
    CONFIG_ENV_VAR,
    missing_azure_settings,
    save_azure_config,
)
from lisa_mcp.runtime import set_transport  # noqa: E402
from lisa_mcp.tools import execution  # noqa: E402
from lisa_mcp.tools import log_analysis  # noqa: E402
from lisa_mcp.tools._repo import find_repo_root  # noqa: E402
from lisa_mcp.tools.execution import _VARIABLE_NAMES  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PASSING_LOG = FIXTURES_DIR / "sample_passing_run.log"
FAILING_LOG = FIXTURES_DIR / "sample_failing_run.log"
SAMPLE_RUNBOOK = FIXTURES_DIR / "sample_runbook.yml"


def _call(tool_name: str, **kwargs: object) -> str:
    """Invoke a registered MCP tool by name and return its string result."""
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    if tool_name not in tools:
        raise AssertionError(
            f"Tool '{tool_name}' not found. Available: {sorted(tools)}"
        )
    # Access the underlying function
    fn = tools[tool_name].fn
    return fn(**kwargs)


# ======================================================================
# Test Authoring tools (7)
# ======================================================================


class TestGetTestWriterGuidelines(unittest.TestCase):
    def test_returns_guidelines(self) -> None:
        result = _call("lisa_get_test_writer_guidelines")
        self.assertIn("LISA", result)
        # Should contain workflow stages
        self.assertTrue(
            "gather" in result.lower()
            or "research" in result.lower()
            or "design" in result.lower(),
            "Guidelines should mention the workflow stages",
        )

    def test_returns_nonempty_string(self) -> None:
        result = _call("lisa_get_test_writer_guidelines")
        self.assertGreater(len(result), 100)


class TestScaffoldTestSuite(unittest.TestCase):
    def test_generates_class(self) -> None:
        result = _call(
            "lisa_scaffold_test_suite",
            area="network",
            class_name="SriovValidation",
            description="Validate SR-IOV VF creation",
        )
        self.assertIn("class SriovValidation(TestSuite)", result)
        self.assertIn('area="network"', result)
        self.assertIn("verify_sriov_validation", result)

    def test_custom_category(self) -> None:
        result = _call(
            "lisa_scaffold_test_suite",
            area="perf",
            class_name="PerfBench",
            description="Perf benchmarks",
            category="performance",
        )
        self.assertIn('category="performance"', result)

    def test_snake_case_conversion(self) -> None:
        result = _call(
            "lisa_scaffold_test_suite",
            area="gpu",
            class_name="GPUDriverCheck",
            description="Check GPU driver",
        )
        self.assertIn("verify_gpu_driver_check", result)

    def test_hostile_description_cannot_break_the_docstring(self) -> None:
        """A `\"\"\"` in the description used to terminate the literal."""
        payloads = [
            'ok"""\nimport os\nos.system("id")\nx = """',
            "trailing backslash \\",
            'nested """ quotes """ everywhere',
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                result = _call(
                    "lisa_scaffold_test_suite",
                    area="demo",
                    class_name="Demo",
                    description=payload,
                )
                code = result.split("```python")[1].split("```")[0]
                compile(code, "<generated>", "exec")

    def test_hostile_class_name_is_rejected(self) -> None:
        result = _call(
            "lisa_scaffold_test_suite",
            area="demo",
            class_name="Demo): pass\nimport os",
            description="ok",
        )
        self.assertIn("valid Python identifier", result)

    def test_python_keywords_are_rejected(self) -> None:
        """str.isidentifier() returns True for keywords; the compiler disagrees."""
        for name in ("class", "None", "lambda", "import"):
            with self.subTest(name=name):
                result = _call(
                    "lisa_scaffold_test_suite",
                    area="demo",
                    class_name=name,
                    description="ok",
                )
                self.assertIn("valid Python identifier", result)
                self.assertNotIn("```python", result)


class TestScaffoldTestCase(unittest.TestCase):
    def test_hostile_description_cannot_break_the_docstring(self) -> None:
        for payload in ('ok"""\nimport os\n"""', "trailing backslash \\"):
            with self.subTest(payload=payload):
                result = _call(
                    "lisa_scaffold_test_case",
                    area="demo",
                    method_name="verify_x",
                    description=payload,
                )
                code = result.split("```python")[1].split("```")[0]
                # The snippet is a class member, so compile it inside a class.
                compile(
                    "class _T:\n"
                    + "\n".join(f"    {line}" for line in code.splitlines()),
                    "<generated>",
                    "exec",
                )

    def test_requirement_symbols_must_be_identifiers(self) -> None:
        """These land in generated source as bare names."""
        cases = [
            {"supported_os": "Posix], evil_expression"},
            {"supported_os": "Posix", "supported_features": "Gpu], another_evil"},
            {"supported_os": "__import__('os').system('id')"},
            {"supported_os": "class"},
            {"supported_os": "Posix", "supported_features": "lambda"},
        ]
        for extra in cases:
            with self.subTest(**extra):
                result = _call(
                    "lisa_scaffold_test_case",
                    area="demo",
                    method_name="verify_x",
                    description="ok",
                    **extra,
                )
                self.assertIn("must be Python symbol names", result)
                self.assertNotIn("```python", result)

    def test_basic_case(self) -> None:
        result = _call(
            "lisa_scaffold_test_case",
            area="storage",
            method_name="verify_disk_resize",
            description="Verify disk resize works",
        )
        self.assertIn("def verify_disk_resize", result)
        self.assertIn("priority=2", result)

    def test_with_features_and_requirements(self) -> None:
        result = _call(
            "lisa_scaffold_test_case",
            area="network",
            method_name="verify_sriov_failover",
            description="Test SR-IOV failover",
            priority=1,
            supported_features="Sriov,NetworkInterface",
            min_nic_count=2,
        )
        self.assertIn("priority=1", result)
        self.assertIn("Sriov", result)
        self.assertIn("NetworkInterface", result)
        self.assertIn("min_nic_count=2", result)

    def test_auto_prefix(self) -> None:
        result = _call(
            "lisa_scaffold_test_case",
            area="kernel",
            method_name="boot_time",
            description="Measure boot time",
        )
        self.assertIn("def verify_boot_time", result)


class TestGenerateRunbook(unittest.TestCase):
    def test_azure_runbook(self) -> None:
        result = _call(
            "lisa_generate_runbook",
            platform="azure",
            area="provisioning",
            max_priority=1,
            location="westus2",
        )
        self.assertIn("type: azure", result)
        self.assertIn("subscription_id", result)
        self.assertIn("provisioning", result)
        self.assertIn("westus2", result)
        self.assertIn("[0, 1]", result)

    def test_local_runbook(self) -> None:
        """`local` is a node type: the platform must come out as `ready`."""
        result = _call("lisa_generate_runbook", platform="local")
        doc = yaml.safe_load(result.split("```yaml")[1].split("```")[0])
        self.assertEqual([p["type"] for p in doc["platform"]], ["ready"])
        nodes = doc["environment"]["environments"][0]["nodes"]
        self.assertEqual([n["type"] for n in nodes], ["local"])
        self.assertNotIn("subscription_id", result)

    def test_with_image(self) -> None:
        result = _call(
            "lisa_generate_runbook",
            platform="azure",
            image="canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest",
        )
        self.assertIn("canonical", result)
        self.assertIn("22_04-lts-gen2", result)

    def test_with_test_names(self) -> None:
        result = _call(
            "lisa_generate_runbook",
            test_names="smoke_test,verify_reboot",
        )
        self.assertIn("smoke_test", result)
        self.assertIn("verify_reboot", result)


class TestValidateRunbook(unittest.TestCase):
    def test_valid_runbook(self) -> None:
        result = _call(
            "lisa_validate_runbook",
            runbook_content=SAMPLE_RUNBOOK.read_text(),
        )
        self.assertIn("valid", result.lower())

    def test_invalid_yaml(self) -> None:
        result = _call("lisa_validate_runbook", runbook_content=": {bad yaml: [")
        self.assertIn("error", result.lower())

    def test_missing_platform(self) -> None:
        result = _call(
            "lisa_validate_runbook",
            runbook_content="testcase:\n  - criteria:\n      area: demo\n",
        )
        self.assertIn("platform", result.lower())

    def test_missing_testcase(self) -> None:
        result = _call(
            "lisa_validate_runbook",
            runbook_content="platform:\n  - type: azure\n",
        )
        self.assertIn("testcase", result.lower())

    def test_unknown_platform_type(self) -> None:
        result = _call(
            "lisa_validate_runbook",
            runbook_content=(
                "platform:\n  - type: unknown_platform\n"
                "testcase:\n  - criteria:\n      area: test\n"
            ),
        )
        self.assertIn("unknown_platform", result)


class TestListTestRequirements(unittest.TestCase):
    def test_nonexistent_test(self) -> None:
        result = _call(
            "lisa_list_test_requirements", test_name="nonexistent_test_xyz_123"
        )
        self.assertIn("not found", result.lower())


class TestWriteTest(unittest.TestCase):
    def test_generates_design_plan(self) -> None:
        result = _call(
            "lisa_write_test",
            description="SR-IOV VFs are created for each NIC",
            area="network",
            feature="Sriov",
        )
        self.assertIn("Design Plan", result)
        self.assertIn("Arrange", result)
        self.assertIn("Act", result)
        self.assertIn("Assert", result)
        self.assertIn("Structured Metadata", result)

    def test_custom_names(self) -> None:
        result = _call(
            "lisa_write_test",
            description="disk hotplug works",
            area="storage",
            class_name="DiskHotplug",
            method_name="verify_disk_hotplug",
        )
        self.assertIn("DiskHotplug", result)
        self.assertIn("verify_disk_hotplug", result)

    def test_mark_dirty_detection(self) -> None:
        result = _call(
            "lisa_write_test",
            description="kernel module loads after reboot",
            area="kernel",
        )
        self.assertIn("mark_dirty", result)

    def test_structured_metadata(self) -> None:
        result = _call(
            "lisa_write_test",
            description="VF count stable after VM hot-resize",
            area="network",
            feature="Sriov",
            tier=1,
            platform="azure",
            distro_notes="Ubuntu 24.04 only",
        )
        self.assertIn("Structured Metadata", result)
        self.assertIn('"area": "network"', result)
        self.assertIn('"feature": "Sriov"', result)
        self.assertIn('"tier": 1', result)
        self.assertIn('"platform": "azure"', result)

    def test_existing_suite_detection(self) -> None:
        result = _call(
            "lisa_write_test",
            description="verify CIFS module is functional",
            area="core",
            feature="storage",
        )
        # Should find the existing storage.py suite and list its methods
        self.assertIn("Existing tests in", result)
        self.assertIn("existing_suites", result)


# ======================================================================
# Log Analysis tools (8)
# ======================================================================


class TestAnalyzeLog(unittest.TestCase):
    def test_passing_log_from_file(self) -> None:
        result = _call("lisa_analyze_log", log_path=str(PASSING_LOG))
        self.assertIn("passed", result.lower())
        self.assertIn("0 failed", result.lower())

    def test_failing_log_from_file(self) -> None:
        result = _call("lisa_analyze_log", log_path=str(FAILING_LOG))
        self.assertIn("failed", result.lower())
        self.assertIn("Kernel", result)

    def test_log_from_content(self) -> None:
        result = _call(
            "lisa_analyze_log",
            log_content="smoke_test | PASSED | ok\nverify_x | FAILED | boom\n",
        )
        self.assertIn("passed", result.lower())
        self.assertIn("1 failed", result.lower())

    def test_empty_log(self) -> None:
        result = _call("lisa_analyze_log", log_content="nothing relevant here\n")
        self.assertIn("0 passed", result.lower())

    def test_no_input_returns_error(self) -> None:
        result = _call("lisa_analyze_log")
        self.assertIn("error", result.lower())

    def test_nonexistent_file(self) -> None:
        result = _call("lisa_analyze_log", log_path="/nonexistent/path/log.txt")
        self.assertIn("error", result.lower())


class TestExplainFailure(unittest.TestCase):
    def test_kernel_panic(self) -> None:
        result = _call(
            "lisa_explain_failure",
            failure_text="Kernel panic - not syncing: VFS: Unable to mount root fs",
        )
        self.assertIn("Kernel", result)

    def test_ssh_failure(self) -> None:
        result = _call(
            "lisa_explain_failure",
            failure_text="TcpConnectionException: failed to connect to 10.0.0.5:22",
        )
        self.assertIn("Connectivity", result)

    def test_assertion_failure(self) -> None:
        result = _call(
            "lisa_explain_failure",
            failure_text="AssertionError: Expected 2 but got 1",
        )
        self.assertIn("Assertion", result)

    def test_timeout(self) -> None:
        result = _call(
            "lisa_explain_failure",
            failure_text="Operation timed out after 300 seconds",
        )
        self.assertIn("Timeout", result)

    def test_provisioning_error(self) -> None:
        result = _call(
            "lisa_explain_failure",
            failure_text="OverconstrainedAllocationRequest: cannot allocate",
        )
        self.assertIn("Provisioning", result)

    def test_skipped(self) -> None:
        result = _call(
            "lisa_explain_failure",
            failure_text="SkippedException: GPU not available",
        )
        self.assertIn("Skipped", result)

    def test_unknown_failure(self) -> None:
        result = _call(
            "lisa_explain_failure",
            failure_text="Something completely unexpected happened",
        )
        # Should return a classification of some kind
        self.assertIn("Failure Classification", result)


class TestSummarizeRun(unittest.TestCase):
    def test_passing_run(self) -> None:
        result = _call("lisa_summarize_run", log_path=str(PASSING_LOG))
        self.assertIn("Passed", result)
        self.assertIn("0", result)  # 0 failed

    def test_failing_run(self) -> None:
        result = _call("lisa_summarize_run", log_path=str(FAILING_LOG))
        self.assertIn("Failed", result)
        self.assertIn("Kernel", result)

    def test_from_content(self) -> None:
        result = _call(
            "lisa_summarize_run",
            log_content="test_a | PASSED | ok\ntest_b | PASSED | ok\n",
        )
        self.assertIn("2", result)


class TestDownloadLogs(unittest.TestCase):
    def test_rejects_http(self) -> None:
        result = _call(
            "lisa_download_logs",
            url="http://example.com/logs.tar.gz",
        )
        self.assertIn("Error", result)
        self.assertIn("HTTPS", result)

    def test_rejects_bad_url(self) -> None:
        result = _call(
            "lisa_download_logs",
            url="not-a-url",
        )
        self.assertIn("Error", result)

    def test_no_args_investigation(self) -> None:
        result = _call("lisa_start_log_investigation")
        self.assertIn("Error", result)
        self.assertIn("log_path", result)


class TestStartLogInvestigation(unittest.TestCase):
    def test_returns_investigation_context(self) -> None:
        result = _call(
            "lisa_start_log_investigation",
            log_path=str(FIXTURES_DIR),
            error_message="TcpConnectionException",
        )
        self.assertIn("Log Files", result)
        self.assertIn("Pattern Hit Counts", result)
        self.assertIn("Initial Error Search", result)
        self.assertIn("Next Steps", result)

    def test_bad_path(self) -> None:
        result = _call(
            "lisa_start_log_investigation",
            log_path="/nonexistent/path/12345",
        )
        self.assertIn("Error", result)


class TestGetLogAnalysisPrompts(unittest.TestCase):
    def test_returns_prompts(self) -> None:
        result = _call("lisa_get_log_analysis_prompts")
        # Should contain the agent strategy headings
        self.assertIn("Log Search", result)
        self.assertIn("Code Search", result)
        self.assertIn("Final Answer", result)

    def test_nonempty(self) -> None:
        result = _call("lisa_get_log_analysis_prompts")
        self.assertGreater(len(result), 500)


class TestSearchLogFiles(unittest.TestCase):
    def test_search_in_fixtures(self) -> None:
        result = _call(
            "lisa_search_log_files",
            search_string="Kernel panic",
            path=str(FIXTURES_DIR),
        )
        self.assertIn("match", result.lower())
        self.assertIn("Kernel panic", result)

    def test_search_no_match(self) -> None:
        result = _call(
            "lisa_search_log_files",
            search_string="ZZZ_UNIQUE_STRING_NOT_IN_LOGS_ZZZ",
            path=str(FIXTURES_DIR),
        )
        self.assertIn("no match", result.lower())

    def test_bad_directory(self) -> None:
        result = _call(
            "lisa_search_log_files",
            search_string="test",
            path="/nonexistent/dir/xyz",
        )
        self.assertIn("error", result.lower())

    def test_extension_filter(self) -> None:
        result = _call(
            "lisa_search_log_files",
            search_string="platform",
            path=str(FIXTURES_DIR),
            file_extensions=".log",
        )
        # Should find matches only in .log files
        if "match" in result.lower():
            self.assertIn(".log", result)


class TestReadLogFile(unittest.TestCase):
    def test_read_passing_log(self) -> None:
        result = _call("lisa_read_log_file", file_path=str(PASSING_LOG))
        self.assertIn("lisa_runner", result)
        self.assertIn("Starting LISA", result)

    def test_read_range(self) -> None:
        result = _call(
            "lisa_read_log_file",
            file_path=str(FAILING_LOG),
            start_line=10,
            line_count=5,
        )
        # Should contain line numbers
        self.assertIn("(10):", result)
        self.assertIn("(14):", result)

    def test_bad_file(self) -> None:
        result = _call("lisa_read_log_file", file_path="/nonexistent/file.log")
        self.assertIn("error", result.lower())


class TestListLogFiles(unittest.TestCase):
    def test_list_fixtures(self) -> None:
        result = _call("lisa_list_log_files", folder_path=str(FIXTURES_DIR))
        self.assertIn("sample_passing_run.log", result)
        self.assertIn("sample_failing_run.log", result)

    def test_extension_filter(self) -> None:
        result = _call(
            "lisa_list_log_files",
            folder_path=str(FIXTURES_DIR),
            file_extensions=".yml",
        )
        self.assertIn("sample_runbook.yml", result)
        self.assertNotIn(".log", result)

    def test_bad_directory(self) -> None:
        result = _call("lisa_list_log_files", folder_path="/nonexistent/dir/xyz")
        self.assertIn("error", result.lower())


# ======================================================================
# Bug Fixing / Debugging tools (3)
# ======================================================================


class TestDiagnoseBug(unittest.TestCase):
    def test_diagnose_with_assertion(self) -> None:
        result = _call(
            "lisa_diagnose_bug",
            test_name="verify_sriov_basic",
            failure_log=(
                "AssertionError: Expected 2 SRIOV VF devices but found 1\n"
                "assert_that(vf_count).is_equal_to(2)"
            ),
        )
        self.assertIn("Assertion", result)
        self.assertIn("verify_sriov_basic", result)

    def test_diagnose_with_connectivity(self) -> None:
        result = _call(
            "lisa_diagnose_bug",
            test_name="verify_reboot",
            failure_log="TcpConnectionException: failed to connect to 10.0.0.5:22",
        )
        self.assertIn("Connectivity", result)

    def test_unknown_test(self) -> None:
        result = _call(
            "lisa_diagnose_bug",
            test_name="totally_fake_test_xyz",
            failure_log="some error",
        )
        # Should still provide classification even without source
        self.assertIn("totally_fake_test_xyz", result)


class TestFixRunbook(unittest.TestCase):
    def test_fix_missing_platform(self) -> None:
        result = _call(
            "lisa_fix_runbook",
            runbook_content="testcase:\n  - criteria:\n      area: demo\n",
        )
        self.assertIn("platform", result.lower())
        self.assertIn("fix", result.lower())

    def test_fix_boolean_keep_environment(self) -> None:
        # Implicit concatenation rather than textwrap.dedent("""..."""): the
        # repo pins black 23, newer black hugs a multiline string argument
        # against its parentheses, and the two rewrite each other on every
        # save — which is what kept breaking flake8-black in CI.
        runbook = (
            "platform:\n"
            "  - type: azure\n"
            "    keep_environment: true\n"
            "testcase:\n"
            "  - criteria:\n"
            "      area: demo\n"
        )
        result = _call("lisa_fix_runbook", runbook_content=runbook)
        self.assertIn("always", result)

    def test_fix_platform_as_dict(self) -> None:
        runbook = (
            "platform:\n"
            "  type: azure\n"
            "testcase:\n"
            "  - criteria:\n"
            "      area: demo\n"
        )
        result = _call("lisa_fix_runbook", runbook_content=runbook)
        self.assertIn("list", result.lower())

    def test_valid_runbook_no_fixes(self) -> None:
        result = _call("lisa_fix_runbook", runbook_content=SAMPLE_RUNBOOK.read_text())
        # The sample runbook uses YAML `no` for keep_environment which is
        # parsed as boolean false — the tool fixes it to the string "no".
        # Either "no structural issues" or a fix report is acceptable.
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 10)

    def test_invalid_yaml(self) -> None:
        result = _call("lisa_fix_runbook", runbook_content="{{bad: yaml")
        self.assertIn("error", result.lower())


class TestExplainError(unittest.TestCase):
    def test_tcp_connection(self) -> None:
        result = _call("lisa_explain_error", error_text="TcpConnectionException")
        self.assertIn("TCP", result)
        self.assertIn("SSH", result.upper())

    def test_skipped_exception(self) -> None:
        result = _call("lisa_explain_error", error_text="SkippedException")
        self.assertIn("prerequisite", result.lower())

    def test_quota_exceeded(self) -> None:
        result = _call("lisa_explain_error", error_text="QuotaExceeded")
        self.assertIn("quota", result.lower())

    def test_overconstrained(self) -> None:
        result = _call(
            "lisa_explain_error",
            error_text="OverconstrainedAllocationRequest",
        )
        self.assertIn("allocat", result.lower())

    def test_unknown_error(self) -> None:
        result = _call(
            "lisa_explain_error",
            error_text="CompletelyMadeUpExceptionXyz123",
        )
        # Should still provide some output (from error_patterns.md search)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 10)


# ======================================================================
# Knowledge tools (5)
# ======================================================================


class TestExplainConcept(unittest.TestCase):
    def test_runbook(self) -> None:
        result = _call("lisa_explain_concept", concept="runbook")
        self.assertIn("runbook", result.lower())
        self.assertIn("YAML", result)

    def test_node(self) -> None:
        result = _call("lisa_explain_concept", concept="node")
        self.assertIn("node", result.lower())

    def test_feature(self) -> None:
        result = _call("lisa_explain_concept", concept="feature")
        self.assertIn("feature", result.lower())

    def test_tool(self) -> None:
        result = _call("lisa_explain_concept", concept="tool")
        self.assertIn("tool", result.lower())

    def test_simple_requirement(self) -> None:
        result = _call("lisa_explain_concept", concept="simple_requirement")
        self.assertIn("requirement", result.lower())

    def test_priority(self) -> None:
        result = _call("lisa_explain_concept", concept="priority")
        self.assertIn("0", result)  # T0

    def test_environment(self) -> None:
        result = _call("lisa_explain_concept", concept="environment")
        self.assertIn("environment", result.lower())

    def test_unknown_concept(self) -> None:
        result = _call("lisa_explain_concept", concept="xyzzy_nonexistent_thing")
        self.assertIn("not found", result.lower())

    def test_platform_concept_does_not_teach_node_types_as_platforms(self) -> None:
        """`platform: local` is rejected by the validator, so never list it."""
        import re

        result = _call("lisa_explain_concept", concept="platform")
        listed = re.findall(r"^- `([\w-]+)`", result, re.M)
        self.assertIn("ready", listed)
        self.assertNotIn("local", listed)
        self.assertNotIn("remote", listed)

    def test_builtin_concept_fallbacks_use_the_right_platform_model(self) -> None:
        """These are served when the curated context files are unavailable."""
        from lisa_mcp.tools.knowledge import _BUILTIN_CONCEPTS

        platform = _BUILTIN_CONCEPTS["platform"]
        self.assertIn("ready", platform)
        self.assertIn("node", platform.lower())
        self.assertNotIn("local, remote", _BUILTIN_CONCEPTS["runbook"])


class TestGetApiReference(unittest.TestCase):
    def test_find_testsuite(self) -> None:
        result = _call("lisa_get_api_reference", symbol="TestSuiteMetadata")
        # Should find the decorator
        self.assertTrue(
            "TestSuiteMetadata" in result,
            f"Expected TestSuiteMetadata in result, got: {result[:200]}",
        )

    def test_unknown_symbol(self) -> None:
        result = _call("lisa_get_api_reference", symbol="CompletelyFakeSymbolXyz")
        self.assertIn("not found", result.lower())


class TestFindExamples(unittest.TestCase):
    def test_search_network(self) -> None:
        result = _call("lisa_find_examples", query="network")
        # Should return some results or "no test files"
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 10)

    def test_search_empty_query(self) -> None:
        result = _call("lisa_find_examples", query="a")
        # Too short keyword
        self.assertIsInstance(result, str)


class TestListTools(unittest.TestCase):
    def test_returns_tools(self) -> None:
        result = _call("lisa_list_tools")
        # Should list at least some known tools
        has_content = len(result) > 50
        self.assertTrue(
            has_content,
            f"Expected tool listing, got: {result[:200]}",
        )


class TestListFeatures(unittest.TestCase):
    def test_returns_features(self) -> None:
        result = _call("lisa_list_features")
        has_content = len(result) > 50
        self.assertTrue(
            has_content,
            f"Expected feature listing, got: {result[:200]}",
        )


# ======================================================================
# Test persistence and discovery
# ======================================================================


class TestSaveTest(unittest.TestCase):
    SUITE_DIR = "lisa/microsoft/testsuites"

    def setUp(self) -> None:
        self.repo_root = find_repo_root()
        if not self.repo_root:
            self.skipTest("LISA repo root not found")
        self.created: list[Path] = []

    def tearDown(self) -> None:
        for path in self.created:
            path.unlink(missing_ok=True)

    def _rel(self, name: str) -> str:
        return f"{self.SUITE_DIR}/{name}"

    def test_rejects_absolute_path(self) -> None:
        result = _call(
            "lisa_save_test",
            file_path=str(Path.home() / "evil.py"),
            code="x = 1",
        )
        self.assertIn("must be relative", result)

    def test_rejects_path_traversal(self) -> None:
        result = _call(
            "lisa_save_test",
            file_path="../../evil.py",
            code="x = 1",
        )
        self.assertIn("outside the test-suite directories", result)

    def test_rejects_framework_and_server_paths(self) -> None:
        """overwrite=True must not let a caller replace executable code."""
        for hostile in (
            "lisa/platform_.py",
            "mcp/lisa_mcp/server.py",
            "selftests/test_platform.py",
            "noxfile.py",
        ):
            with self.subTest(path=hostile):
                result = _call(
                    "lisa_save_test",
                    file_path=hostile,
                    code="x = 1",
                    overwrite=True,
                )
                self.assertIn("outside the test-suite directories", result)

    def test_server_source_is_untouched_after_attempt(self) -> None:
        assert self.repo_root is not None
        server_py = self.repo_root / "mcp/lisa_mcp/server.py"
        before = server_py.read_bytes()
        _call(
            "lisa_save_test",
            file_path="mcp/lisa_mcp/server.py",
            code="# pwned\n",
            overwrite=True,
        )
        self.assertEqual(server_py.read_bytes(), before)

    def test_rejects_non_python_file(self) -> None:
        result = _call("lisa_save_test", file_path=self._rel("notes.txt"), code="x = 1")
        self.assertIn("must end in .py", result)

    def test_rejects_empty_code(self) -> None:
        result = _call("lisa_save_test", file_path=self._rel("mcp_tmp.py"), code="   ")
        self.assertIn("empty file", result)

    def test_writes_file(self) -> None:
        rel = self._rel("mcp_save_test_sample.py")
        assert self.repo_root is not None
        target = self.repo_root / rel
        self.created.append(target)

        result = _call("lisa_save_test", file_path=rel, code="# sample\nx = 1\n")
        self.assertIn("Saved", result)
        self.assertTrue(target.is_file())

    def test_refuses_overwrite_by_default(self) -> None:
        rel = self._rel("mcp_save_test_sample.py")
        assert self.repo_root is not None
        target = self.repo_root / rel
        self.created.append(target)

        _call("lisa_save_test", file_path=rel, code="x = 1\n")
        result = _call("lisa_save_test", file_path=rel, code="x = 2\n")
        self.assertIn("already exists", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 1\n")

        result = _call("lisa_save_test", file_path=rel, code="x = 2\n", overwrite=True)
        self.assertIn("Saved", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 2\n")


class TestListTests(unittest.TestCase):
    def test_lists_without_filters(self) -> None:
        result = _call("lisa_list_tests", max_results=5)
        self.assertIn("matching test case", result)

    def test_unknown_area_returns_no_match(self) -> None:
        result = _call("lisa_list_tests", area="definitely_not_an_area")
        self.assertIn("No test cases matched", result)

    def test_tier_filter_reports_priority(self) -> None:
        result = _call("lisa_list_tests", tier=0, max_results=5)
        if "No test cases matched" not in result:
            self.assertIn("P0", result)


# ======================================================================
# Execution and local configuration
# ======================================================================


class TestExecutionConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._previous = os.environ.get(CONFIG_ENV_VAR)
        os.environ[CONFIG_ENV_VAR] = str(Path(self._tmp_dir.name) / "mcp_config.yaml")

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop(CONFIG_ENV_VAR, None)
        else:
            os.environ[CONFIG_ENV_VAR] = self._previous
        self._tmp_dir.cleanup()

    def test_get_config_reports_missing_settings(self) -> None:
        result = _call("lisa_get_config")
        self.assertIn("subscription_id", result)
        self.assertIn("lisa_save_config", result)

    def test_defaults_are_applied(self) -> None:
        result = _call("lisa_get_config")
        self.assertIn("eastus", result)
        self.assertIn("Standard_DS2_v2", result)

    def test_save_config_persists_settings(self) -> None:
        result = _call(
            "lisa_save_config",
            subscription_id="00000000-0000-0000-0000-000000000000",
            resource_group="lisa-tests-rg",
        )
        self.assertIn("Saved", result)
        self.assertEqual(missing_azure_settings(), [])

    def test_save_config_without_values_is_noop(self) -> None:
        result = _call("lisa_save_config")
        self.assertIn("nothing was written", result)

    def test_run_prompts_for_missing_config(self) -> None:
        result = _call(
            "lisa_run", runbook_path="lisa/examples/runbook/hello_world_azure.yml"
        )
        self.assertIn("not configured", result)

    def test_local_runbook_does_not_require_azure_config(self) -> None:
        # hello_world.yml targets a local node, so Azure settings are irrelevant.
        completed = subprocess.CompletedProcess(
            args=["lisa"], returncode=0, stdout="done", stderr=""
        )
        with mock.patch.object(execution.subprocess, "run", return_value=completed):
            result = _call(
                "lisa_run", runbook_path="lisa/examples/runbook/hello_world.yml"
            )
        self.assertNotIn("not configured", result)
        self.assertIn("succeeded", result)

    def test_run_reports_unknown_runbook(self) -> None:
        result = _call("lisa_run", runbook_path="does/not/exist.yml")
        self.assertIn("Runbook not found", result)

    def test_resource_group_maps_to_lisa_variable_name(self) -> None:
        # LISA runbooks declare resource_group_name, the config key is
        # resource_group.
        self.assertEqual(_VARIABLE_NAMES["resource_group"], "resource_group_name")

    def test_malformed_config_file_reads_as_empty(self) -> None:
        """A YAML list or scalar must not reach callers that expect a dict."""
        from lisa_mcp.config import load_config

        config = Path(os.environ[CONFIG_ENV_VAR])
        for content in ("- just\n- a\n- list\n", "just a string\n", "42\n"):
            config.write_text(content, encoding="utf-8")
            self.assertEqual(load_config(), {})
            # The tools call .get on it, so this must not raise.
            self.assertIn("not configured", _call("lisa_get_config"))


class TestRunVariableValidation(unittest.TestCase):
    """Malformed variables must be rejected before a subprocess is spawned."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._previous = os.environ.get(CONFIG_ENV_VAR)
        config = Path(self._tmp_dir.name) / "mcp_config.yaml"
        os.environ[CONFIG_ENV_VAR] = str(config)
        save_azure_config(
            {
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "resource_group": "unit-test-rg",
            }
        )
        # Any spawn attempt is a bug: these inputs must never get that far.
        self._spawn_patch = mock.patch.object(
            execution.subprocess,
            "run",
            side_effect=AssertionError("subprocess must not be spawned"),
        )
        self._spawn_patch.start()

    def tearDown(self) -> None:
        self._spawn_patch.stop()
        if self._previous is None:
            os.environ.pop(CONFIG_ENV_VAR, None)
        else:
            os.environ[CONFIG_ENV_VAR] = self._previous
        self._tmp_dir.cleanup()

    def test_rejects_malformed_variables(self) -> None:
        for value in ("admin_username", "9bad:value", "name:", "; rm -rf /"):
            with self.subTest(value=value):
                result = _call(
                    "lisa_run",
                    runbook_path="lisa/examples/runbook/hello_world.yml",
                    variables=value,
                )
                self.assertIn("Invalid variable", result)

    def test_accepts_secret_variable_form(self) -> None:
        args, error = execution._parse_variables("s:token:abc name:value")
        self.assertIsNone(error)
        self.assertEqual(args, ["-v", "s:token:abc", "-v", "name:value"])

    def test_unmatched_quote_returns_guidance(self) -> None:
        """shlex raises on this; it must not escape as an MCP transport error."""
        args, error = execution._parse_variables('name:"unterminated')
        self.assertEqual(args, [])
        self.assertIsNotNone(error)
        self.assertIn("name:value", str(error))

        result = _call(
            "lisa_run",
            runbook_path="lisa/examples/runbook/hello_world.yml",
            variables='name:"unterminated',
        )
        self.assertIn("name:value", result)


class TestRunOutputRedaction(unittest.TestCase):
    """The run report must not echo the variables handed to LISA."""

    CANARY = "11111111-canary-dead-beef-222222222222"

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._previous = os.environ.get(CONFIG_ENV_VAR)
        os.environ[CONFIG_ENV_VAR] = str(Path(self._tmp_dir.name) / "mcp_config.yaml")
        save_azure_config(
            {"subscription_id": self.CANARY, "resource_group": "unit-test-rg"}
        )

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop(CONFIG_ENV_VAR, None)
        else:
            os.environ[CONFIG_ENV_VAR] = self._previous
        self._tmp_dir.cleanup()

    def _run_with_fake_subprocess(self, returncode: int, stdout: str) -> str:
        completed = subprocess.CompletedProcess(
            args=["lisa"], returncode=returncode, stdout=stdout, stderr=""
        )
        with mock.patch.object(
            execution.subprocess, "run", return_value=completed
        ) as spawn:
            result = _call(
                "lisa_run",
                runbook_path="lisa/examples/runbook/hello_world.yml",
                variables="s:token:supersecret",
            )
        self._last_command = spawn.call_args[0][0]
        return result

    def test_secrets_are_not_echoed(self) -> None:
        result = self._run_with_fake_subprocess(0, "run finished")
        self.assertNotIn(self.CANARY, result)
        self.assertNotIn("supersecret", result)

    def test_secrets_echoed_by_lisa_are_redacted(self) -> None:
        """LISA's own debug logging prints the variables it was handed."""
        stdout = (
            "INFO variable: subscription_id = " + self.CANARY + "\n"
            "INFO variable: resource_group_name = unit-test-rg\n"
            "DEBUG token=supersecret used for auth\n"
            "INFO run finished\n"
        )
        result = self._run_with_fake_subprocess(0, stdout)
        self.assertNotIn(self.CANARY, result)
        self.assertNotIn("supersecret", result)
        self.assertNotIn("unit-test-rg", result)
        # Surrounding log context must survive so the report stays useful.
        self.assertIn("run finished", result)
        self.assertIn("[redacted]", result)

    def test_redaction_survives_truncation(self) -> None:
        """Truncating first could cut a secret in half and leak the front."""
        filler = "x" * (execution._MAX_LOG_CHARS + 5000)
        result = self._run_with_fake_subprocess(0, self.CANARY + filler + self.CANARY)
        self.assertNotIn(self.CANARY, result)
        self.assertNotIn(self.CANARY[:20], result)

    def test_short_declared_secrets_are_always_redacted(self) -> None:
        """`s:` is the caller saying it is a secret; length is irrelevant."""
        completed = subprocess.CompletedProcess(
            args=["lisa"], returncode=0, stdout="pin=123 tok=ab ok", stderr=""
        )
        with mock.patch.object(execution.subprocess, "run", return_value=completed):
            result = _call(
                "lisa_run",
                runbook_path="lisa/examples/runbook/hello_world.yml",
                variables="s:pin:123 s:tok:ab",
            )
        self.assertNotIn("123", result)
        self.assertNotIn("tok=ab", result)
        self.assertIn("[redacted]", result)

    def test_short_unmarked_values_are_left_alone(self) -> None:
        """Blanking every short token would shred the log it sits in."""
        completed = subprocess.CompletedProcess(
            args=["lisa"], returncode=0, stdout="mode=ab finished ok", stderr=""
        )
        with mock.patch.object(execution.subprocess, "run", return_value=completed):
            result = _call(
                "lisa_run",
                runbook_path="lisa/examples/runbook/hello_world.yml",
                variables="mode:ab",
            )
        self.assertIn("mode=ab", result)

    def test_variables_still_reach_lisa(self) -> None:
        self._run_with_fake_subprocess(0, "run finished")
        joined = " ".join(self._last_command)
        self.assertIn(f"subscription_id:{self.CANARY}", joined)
        self.assertIn("s:token:supersecret", joined)
        # Config key resource_group is translated for the runbook.
        self.assertIn("resource_group_name:unit-test-rg", joined)

    def test_command_is_a_list_never_a_shell_string(self) -> None:
        self._run_with_fake_subprocess(0, "run finished")
        self.assertIsInstance(self._last_command, list)

    def test_debug_flag_adds_switch(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["lisa"], returncode=0, stdout="ok", stderr=""
        )
        with mock.patch.object(
            execution.subprocess, "run", return_value=completed
        ) as spawn:
            _call(
                "lisa_run",
                runbook_path="lisa/examples/runbook/hello_world.yml",
                debug=True,
            )
        self.assertIn("-d", spawn.call_args[0][0])

    def test_failure_is_reported_with_exit_code(self) -> None:
        result = self._run_with_fake_subprocess(1, "boom")
        self.assertIn("failed", result)
        self.assertIn("boom", result)

    def test_windows_unsigned_exit_code_is_normalized(self) -> None:
        # Windows surfaces -1 as 4294967295; the report must show -1.
        result = self._run_with_fake_subprocess(4294967295, "crashed")
        self.assertIn("exit code -1", result)
        self.assertIn("failed", result)
        self.assertNotIn("4294967295", result)

    def test_timeout_is_reported(self) -> None:
        with mock.patch.object(
            execution.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="lisa", timeout=1),
        ):
            result = _call(
                "lisa_run", runbook_path="lisa/examples/runbook/hello_world.yml"
            )
        self.assertIn("exceeded", result)


class TestRunTransportGuard(unittest.TestCase):
    def tearDown(self) -> None:
        set_transport("stdio")

    def test_run_is_blocked_on_sse(self) -> None:
        set_transport("sse")
        result = _call("lisa_run", runbook_path="lisa/examples/runbook/hello_world.yml")
        self.assertIn("not available on a remote MCP server", result)


class TestRunbookPlatformDetection(unittest.TestCase):
    """Only Azure runbooks should be gated on Azure settings."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _types(self, content: str) -> set:
        path = Path(self._tmp_dir.name) / "runbook.yml"
        path.write_text(content, encoding="utf-8")
        return execution._runbook_platform_types(path)

    def test_list_form(self) -> None:
        self.assertEqual(self._types("platform:\n  - type: azure\n"), {"azure"})

    def test_dict_form(self) -> None:
        self.assertEqual(self._types("platform:\n  type: ready\n"), {"ready"})

    def test_local_platform(self) -> None:
        types = self._types("platform:\n  - type: local\n")
        self.assertNotIn("azure", types)

    def test_case_and_whitespace_insensitive(self) -> None:
        self.assertEqual(self._types("platform:\n  - type: '  Azure '\n"), {"azure"})

    def test_missing_platform_is_unknown(self) -> None:
        self.assertEqual(
            self._types("testcase:\n  - criteria:\n      area: demo\n"), set()
        )

    def test_unparseable_runbook_is_unknown(self) -> None:
        self.assertEqual(self._types("platform:\n  - type: azure\n\tbad: tab\n"), set())

    def test_real_runbooks(self) -> None:
        repo_root = find_repo_root()
        if not repo_root:
            self.skipTest("LISA repo root not found")
        local = repo_root / "lisa/examples/runbook/hello_world.yml"
        azure = repo_root / "lisa/examples/runbook/hello_world_azure.yml"
        self.assertNotIn("azure", execution._runbook_platform_types(local))
        self.assertIn("azure", execution._runbook_platform_types(azure))


class TestAzureConfigGate(unittest.TestCase):
    """`lisa_run` must prompt whenever Azure settings could be needed."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _needs_config(self, content: str) -> bool:
        path = Path(self._tmp_dir.name) / "runbook.yml"
        path.write_text(content, encoding="utf-8")
        return execution._needs_azure_config(path)

    def test_azure_platform_is_gated(self) -> None:
        self.assertTrue(self._needs_config("platform:\n  - type: azure\n"))

    def test_declared_non_azure_platform_is_not_gated(self) -> None:
        self.assertFalse(self._needs_config("platform:\n  - type: ready\n"))

    def test_include_based_runbook_is_gated(self) -> None:
        """The platform hides in the include, so it may well be Azure."""
        self.assertTrue(
            self._needs_config('include:\n  - path: "./shared_azure.yml"\n')
        )

    def test_unparseable_runbook_is_gated(self) -> None:
        self.assertTrue(self._needs_config("platform:\n  - type: azure\n\tbad: tab\n"))

    def test_self_hosted_local_nodes_are_not_gated(self) -> None:
        """hello_world.yml style: no platform, nodes declared inline."""
        self.assertFalse(
            self._needs_config(
                "environment:\n"
                "  environments:\n"
                "    - nodes:\n"
                "        - type: local\n"
            )
        )


# ======================================================================
# Cross-cutting: verify all registered tools
# ======================================================================


class TestLogRootSandbox(unittest.TestCase):
    """Log tools must not become an arbitrary file reader over the network."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._prev_root = os.environ.get("LISA_LOG_ROOT")
        self._prev_transport = runtime.get_transport()

    def tearDown(self) -> None:
        runtime.set_transport(self._prev_transport)
        if self._prev_root is None:
            os.environ.pop("LISA_LOG_ROOT", None)
        else:
            os.environ["LISA_LOG_ROOT"] = self._prev_root
        self._tmp_dir.cleanup()

    def test_remote_without_log_root_is_refused(self) -> None:
        os.environ.pop("LISA_LOG_ROOT", None)
        runtime.set_transport("sse")
        resolved, err = log_analysis._resolve_under_log_root(self._tmp_dir.name)
        self.assertIsNone(resolved)
        self.assertIn("LISA_LOG_ROOT", str(err))

    def test_local_without_log_root_is_allowed(self) -> None:
        os.environ.pop("LISA_LOG_ROOT", None)
        runtime.set_transport("stdio")
        resolved, err = log_analysis._resolve_under_log_root(self._tmp_dir.name)
        self.assertIsNone(err)
        self.assertIsNotNone(resolved)

    def test_path_outside_root_is_refused(self) -> None:
        os.environ["LISA_LOG_ROOT"] = self._tmp_dir.name
        outside = str(Path(self._tmp_dir.name).parent / "elsewhere.log")
        resolved, err = log_analysis._resolve_under_log_root(outside)
        self.assertIsNone(resolved)
        self.assertIn("outside", str(err))

    def test_analyze_log_honours_the_sandbox(self) -> None:
        """lisa_analyze_log used to read log_path without any check."""
        os.environ["LISA_LOG_ROOT"] = self._tmp_dir.name
        outside = Path(self._tmp_dir.name).parent / "secret.log"
        outside.write_text("topsecret", encoding="utf-8")
        try:
            result = _call("lisa_analyze_log", log_path=str(outside))
        finally:
            outside.unlink()
        self.assertNotIn("topsecret", result)
        self.assertIn("LISA_LOG_ROOT", result)


class TestDownloadHostGuard(unittest.TestCase):
    """HTTPS alone does not make a download destination safe."""

    def test_loopback_host_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            log_analysis._reject_internal_host("localhost")
        self.assertIn("non-public", str(ctx.exception))

    def test_private_literal_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            log_analysis._reject_internal_host("10.0.0.5")

    def test_link_local_metadata_address_is_rejected(self) -> None:
        """169.254.169.254 is the cloud instance metadata endpoint."""
        with self.assertRaises(ValueError):
            log_analysis._reject_internal_host("169.254.169.254")

    def test_non_global_special_ranges_are_rejected(self) -> None:
        """An explicit blocklist missed shared address space and TEST-NETs."""
        for address in (
            "100.64.1.1",  # RFC 6598 carrier-grade NAT
            "198.18.0.1",  # RFC 2544 benchmarking
            "203.0.113.5",  # TEST-NET-3
            "240.0.0.1",  # reserved for future use
            "192.0.0.170",  # IETF protocol assignments
        ):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    log_analysis._reject_internal_host(address)

    def test_unresolvable_host_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            log_analysis._reject_internal_host("no-such-host.invalid")


class TestArchiveExtraction(unittest.TestCase):
    """Archive members must not be able to write outside the extract dir."""

    def test_symlink_members_are_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "logs.tar"
            with tarfile.open(archive, "w") as tf:
                payload = Path(tmp) / "real.log"
                payload.write_text("hello", encoding="utf-8")
                tf.add(payload, arcname="real.log")

                link = tarfile.TarInfo("escape.log")
                link.type = tarfile.SYMTYPE
                link.linkname = "/etc/passwd"
                tf.addfile(link)

            extract_root = Path(tmp) / "out"
            extract_root.mkdir()
            result = log_analysis._extract_archive(str(archive), str(extract_root))

            extracted = {p.name for p in Path(result).rglob("*")}
            self.assertIn("real.log", extracted)
            self.assertNotIn("escape.log", extracted)

    def test_traversal_member_names_are_rejected(self) -> None:
        """Absolute, dot-dot, and backslash names must all stay contained."""
        with tempfile.TemporaryDirectory() as tmp:
            abs_extract = os.path.abspath(os.path.join(tmp, "extracted"))
            for hostile in (
                "../escape.log",
                "nested/../../escape.log",
                "/etc/passwd",
                "..\\escape.log",
                "nested\\..\\..\\escape.log",
            ):
                self.assertIsNone(
                    log_analysis._safe_extract_target(abs_extract, hostile),
                    f"{hostile!r} should be rejected",
                )

            for benign in ("real.log", "nested/real.log", "a/b/c.log"):
                target = log_analysis._safe_extract_target(abs_extract, benign)
                self.assertIsNotNone(target, f"{benign!r} should be allowed")
                self.assertTrue(str(target).startswith(abs_extract))

    def test_zip_traversal_member_is_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "evil.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("good.log", b"ok")
                zf.writestr("../escape.log", b"pwned")
                zf.writestr("..\\escape2.log", b"pwned")

            extract_root = Path(tmp) / "out"
            extract_root.mkdir()
            result = log_analysis._extract_archive(str(archive), str(extract_root))

            names = {p.name for p in Path(result).rglob("*")}
            self.assertIn("good.log", names)
            self.assertNotIn("escape.log", names)
            self.assertNotIn("escape2.log", names)
            self.assertFalse((Path(tmp) / "escape.log").exists())

    def test_expansion_beyond_budget_is_refused(self) -> None:
        """A download well under the size cap can still be a zip bomb."""
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bomb.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("big.log", b"\0" * (4 * 1024 * 1024))

            extract_root = Path(tmp) / "out"
            extract_root.mkdir()
            with mock.patch.object(log_analysis, "_MAX_EXTRACT_BYTES", 1024):
                with self.assertRaises(ValueError) as ctx:
                    log_analysis._extract_archive(str(archive), str(extract_root))
            self.assertIn("uncompressed limit", str(ctx.exception))
            self.assertFalse((extract_root / "extracted").exists())

    def test_file_count_budget_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "many.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                for i in range(20):
                    zf.writestr(f"log{i}.log", b"x")

            extract_root = Path(tmp) / "out"
            extract_root.mkdir()
            with mock.patch.object(log_analysis, "_MAX_EXTRACT_FILES", 5):
                with self.assertRaises(ValueError) as ctx:
                    log_analysis._extract_archive(str(archive), str(extract_root))
            self.assertIn("files", str(ctx.exception))


class TestDownloadDirPlacement(unittest.TestCase):
    """Downloads must land somewhere the other log tools are allowed to read."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._prev_root = os.environ.get("LISA_LOG_ROOT")
        self._prev_transport = runtime.get_transport()

    def tearDown(self) -> None:
        runtime.set_transport(self._prev_transport)
        if self._prev_root is None:
            os.environ.pop("LISA_LOG_ROOT", None)
        else:
            os.environ["LISA_LOG_ROOT"] = self._prev_root
        self._tmp_dir.cleanup()

    def test_download_dir_is_inside_log_root(self) -> None:
        root = Path(self._tmp_dir.name) / "logs"
        os.environ["LISA_LOG_ROOT"] = str(root)
        created = Path(log_analysis._make_download_dir()).resolve()
        self.assertEqual(created.parent, root.resolve())
        resolved, err = log_analysis._resolve_under_log_root(str(created))
        self.assertIsNone(err)
        self.assertIsNotNone(resolved)

    def test_falls_back_to_temp_without_log_root(self) -> None:
        os.environ.pop("LISA_LOG_ROOT", None)
        runtime.set_transport("stdio")
        created = Path(log_analysis._make_download_dir())
        try:
            self.assertTrue(created.is_dir())
        finally:
            created.rmdir()

    def test_remote_without_log_root_refuses_to_download(self) -> None:
        """Retained 2 GB downloads into temp would let a client fill the disk."""
        os.environ.pop("LISA_LOG_ROOT", None)
        runtime.set_transport("sse")
        with self.assertRaises(ValueError) as ctx:
            log_analysis._make_download_dir()
        self.assertIn("LISA_LOG_ROOT", str(ctx.exception))

    def test_unwritable_log_root_explains_itself(self) -> None:
        """A `:ro` mount must not surface as a bare PermissionError."""
        os.environ["LISA_LOG_ROOT"] = str(Path(self._tmp_dir.name) / "logs")
        with mock.patch.object(
            log_analysis.tempfile, "mkdtemp", side_effect=PermissionError(13, "denied")
        ):
            with self.assertRaises(ValueError) as ctx:
                log_analysis._make_download_dir()
        self.assertIn("writable", str(ctx.exception))
        self.assertIn("read-only", str(ctx.exception))


class TestDownloadRedirectGuard(unittest.TestCase):
    """The SSRF check has to survive a redirect, not just the first URL."""

    def test_redirect_to_internal_address_is_rejected(self) -> None:
        handler = log_analysis._GuardedRedirectHandler()
        with self.assertRaises(ValueError) as ctx:
            handler.redirect_request(
                urllib.request.Request("https://example.com/logs.tar.gz"),
                None,
                302,
                "Found",
                {},
                "https://169.254.169.254/latest/meta-data/",
            )
        self.assertIn("non-public", str(ctx.exception))

    def test_redirect_to_plain_http_is_rejected(self) -> None:
        handler = log_analysis._GuardedRedirectHandler()
        with self.assertRaises(ValueError) as ctx:
            handler.redirect_request(
                urllib.request.Request("https://example.com/logs.tar.gz"),
                None,
                302,
                "Found",
                {},
                "http://example.com/logs.tar.gz",
            )
        self.assertIn("HTTPS", str(ctx.exception))

    def test_opener_installs_the_guard(self) -> None:
        """A plain urlopen would follow redirects without re-checking."""
        import inspect

        source = inspect.getsource(log_analysis._download_url_to_dir)
        self.assertIn("_open_download(req)", source)
        self.assertNotIn("urlopen(", source)


class TestDnsRebindingGuard(unittest.TestCase):
    """The address that passed the check must be the address connected to."""

    def test_resolve_returns_the_checked_address(self) -> None:
        address = log_analysis._resolve_public_address("example.com")
        parsed = ipaddress.ip_address(address)
        self.assertFalse(parsed.is_private)
        self.assertFalse(parsed.is_loopback)

    def test_resolve_rejects_internal_targets(self) -> None:
        for hostname in ("localhost", "127.0.0.1", "169.254.169.254", "10.0.0.5"):
            with self.assertRaises(ValueError, msg=hostname):
                log_analysis._resolve_public_address(hostname)

    def test_connection_revalidates_at_connect_time(self) -> None:
        """Re-resolving inside connect() is what removes the TOCTOU window."""
        conn = log_analysis._PinnedHTTPSConnection("localhost", 443)
        self.assertEqual(
            conn._create_connection,
            conn._connect_to_validated_address,
        )
        with self.assertRaises(ValueError) as ctx:
            conn._create_connection(("localhost", 443), 5, None)
        self.assertIn("non-public", str(ctx.exception))

    def test_pinned_handler_is_installed_in_the_opener(self) -> None:
        import inspect

        source = inspect.getsource(log_analysis._open_download)
        self.assertIn("_PinnedHTTPSHandler()", source)


class TestSymlinkEscape(unittest.TestCase):
    """A symlink planted inside the root must not read through it."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._prev_root = os.environ.get("LISA_LOG_ROOT")

    def tearDown(self) -> None:
        if self._prev_root is None:
            os.environ.pop("LISA_LOG_ROOT", None)
        else:
            os.environ["LISA_LOG_ROOT"] = self._prev_root
        self._tmp_dir.cleanup()

    def test_symlinked_file_is_rejected(self) -> None:
        base = Path(self._tmp_dir.name)
        root = base / "logs"
        root.mkdir()
        secret = base / "secret.log"
        secret.write_text("SENTINEL-LEAKED-CONTENT", encoding="utf-8")
        link = root / "innocent.log"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted on this host")

        os.environ["LISA_LOG_ROOT"] = str(root)
        self.assertFalse(log_analysis._within_log_root(str(link)))
        # The search term cannot double as the leak canary: the "no matches"
        # reply echoes the term back, so a naive assertion always trips.
        result = _call(
            "lisa_search_log_files", path=str(root), search_string="SENTINEL"
        )
        self.assertIn("No matches", result)
        self.assertNotIn("SENTINEL-LEAKED-CONTENT", result)
        self.assertNotIn("innocent.log", result)


class TestGeneratedArtifactSafety(unittest.TestCase):
    """Hostile input must never corrupt a generated artifact.

    The tools interpolate caller text into Python source, YAML, and file
    paths. Each of those has been a real defect, so this asserts the
    invariant across every payload rather than one case at a time.
    """

    PAYLOADS = {
        "docstring_breakout": 'ok"""\nimport os\nos.system("id")\nx = """',
        "trailing_backslash": "ends with backslash \\",
        "newline_code": "ok\nimport os\nos.system('id')",
        "yaml_break": "demo: injected",
        "yaml_block": "demo\nplatform:\n  - type: azure",
        "traversal": "../../../mcp/lisa_mcp",
        "abs_path": "/etc",
        "format_braces": "{0} {x} {{y}}",
        "quotes": "he said \"hi\" and 'bye'",
        "nul": "ok\x00evil",
        "keyword": "class",
        "keyword_soft": "None",
        "long": "A" * 3000,
        "empty": "",
        "only_space": "   ",
        "punct_only": "!!! ??? ---",
    }
    SUITE_ROOTS = ("lisa/microsoft/testsuites", "lisa/examples/testsuites")

    @staticmethod
    def _block(text: str, lang: str) -> Optional[str]:
        marker = f"```{lang}"
        return text.split(marker)[1].split("```")[0] if marker in text else None

    def _assert_contained(self, path: str) -> None:
        norm = PurePosixPath(str(path).replace("\\", "/")).as_posix()
        self.assertNotIn("..", norm.split("/"), f"escapes: {path!r}")
        self.assertTrue(
            any(norm.startswith(root) for root in self.SUITE_ROOTS),
            f"outside test-suite roots: {path!r}",
        )

    def test_scaffolded_suite_always_compiles(self) -> None:
        for name, payload in self.PAYLOADS.items():
            for field in ("area", "class_name", "description", "category"):
                kwargs = {
                    "area": "demo",
                    "class_name": "Demo",
                    "description": "ok",
                    "category": "functional",
                }
                kwargs[field] = payload
                with self.subTest(payload=name, field=field):
                    result = _call("lisa_scaffold_test_suite", **kwargs)
                    code = self._block(result, "python")
                    if code is None:
                        continue  # rejected with a validation message
                    compile(code, "<generated>", "exec")
                    for match in re.finditer(r"Suggested file path: (\S+)", result):
                        self._assert_contained(match.group(1))

    def test_scaffolded_case_always_compiles(self) -> None:
        for name, payload in self.PAYLOADS.items():
            for field in ("area", "method_name", "description", "supported_os"):
                kwargs = {
                    "area": "demo",
                    "method_name": "verify_x",
                    "description": "ok",
                    "supported_os": "Posix",
                }
                kwargs[field] = payload
                with self.subTest(payload=name, field=field):
                    result = _call("lisa_scaffold_test_case", **kwargs)
                    code = self._block(result, "python")
                    if code is None:
                        continue
                    body = "\n".join(f"    {line}" for line in code.splitlines())
                    compile(f"class _T:\n{body}", "<generated>", "exec")

    def test_write_test_metadata_is_directly_usable(self) -> None:
        """Callers paste class_name/method_name straight into source."""
        # A narrower matrix than the other cases: every call scans the repo,
        # and only these payloads stress name and path derivation.
        payloads = {
            key: self.PAYLOADS[key]
            for key in (
                "docstring_breakout",
                "traversal",
                "punct_only",
                "only_space",
                "nul",
            )
        }
        for name, payload in payloads.items():
            for field in ("description", "area", "class_name"):
                kwargs = {"description": "verify something", "area": "demo"}
                kwargs[field] = payload
                with self.subTest(payload=name, field=field):
                    result = _call("lisa_write_test", **kwargs)
                    for raw in re.findall(r"```json\n(.*?)```", result, re.S):
                        meta = json.loads(raw)
                        for key in ("class_name", "method_name"):
                            value = meta.get(key)
                            if value is not None:
                                self.assertTrue(
                                    str(value).isidentifier()
                                    and not keyword.iskeyword(str(value)),
                                    f"{key}={value!r} is not usable as a name",
                                )
                        if meta.get("file_path"):
                            self._assert_contained(meta["file_path"])

    def test_generated_runbook_structure_survives(self) -> None:
        for name, payload in self.PAYLOADS.items():
            for field in ("area", "tags", "test_names", "location", "vm_size"):
                kwargs = {"platform": "local", "area": "demo"}
                kwargs[field] = payload
                with self.subTest(payload=name, field=field):
                    result = _call("lisa_generate_runbook", **kwargs)
                    text = self._block(result, "yaml")
                    if text is None:
                        continue
                    doc = yaml.safe_load(text)
                    self.assertEqual(
                        [p["type"] for p in doc.get("platform", [])], ["ready"]
                    )

    def test_parsers_never_raise_on_hostile_input(self) -> None:
        """An escaping exception becomes an MCP transport error, not a reply."""
        for name, payload in self.PAYLOADS.items():
            for tool in ("lisa_validate_runbook", "lisa_fix_runbook"):
                with self.subTest(payload=name, tool=tool):
                    self.assertIsInstance(_call(tool, runbook_content=payload), str)
            with self.subTest(payload=name, tool="lisa_save_test"):
                result = _call("lisa_save_test", file_path=payload, code="x = 1")
                self.assertIsInstance(result, str)
                self.assertNotIn("Saved", result)


class TestToolRegistration(unittest.TestCase):
    EXPECTED_TOOLS = {
        # test_writer
        "lisa_get_test_writer_guidelines",
        "lisa_scaffold_test_suite",
        "lisa_scaffold_test_case",
        "lisa_list_test_requirements",
        "lisa_write_test",
        "lisa_save_test",
        "lisa_list_tests",
        # runbook
        "lisa_generate_runbook",
        "lisa_validate_runbook",
        "lisa_fix_runbook",
        # log_analysis
        "lisa_analyze_log",
        "lisa_explain_failure",
        "lisa_summarize_run",
        "lisa_download_logs",
        "lisa_start_log_investigation",
        "lisa_get_log_analysis_prompts",
        "lisa_search_log_files",
        "lisa_read_log_file",
        "lisa_list_log_files",
        "lisa_diagnose_bug",
        # execution
        "lisa_run",
        "lisa_get_config",
        "lisa_save_config",
        # knowledge
        "lisa_explain_concept",
        "lisa_get_api_reference",
        "lisa_find_examples",
        "lisa_list_tools",
        "lisa_list_features",
    }

    def test_all_tools_registered(self) -> None:
        registered = {t.name for t in mcp._tool_manager.list_tools()}
        missing = self.EXPECTED_TOOLS - registered
        self.assertEqual(
            missing,
            set(),
            f"Missing tools: {missing}",
        )

    def test_tool_count(self) -> None:
        count = len(mcp._tool_manager.list_tools())
        self.assertEqual(count, 29, f"Expected 29 tools, got {count}")

    def test_all_tools_callable(self) -> None:
        """Every registered tool should have a callable function."""
        for tool in mcp._tool_manager.list_tools():
            self.assertTrue(
                callable(tool.fn),
                f"Tool '{tool.name}' is not callable",
            )


if __name__ == "__main__":
    unittest.main()
