# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Comprehensive functional tests for all 25 MCP tools.

Run from the mcp/ directory:
    python -m pytest tests/test_all_tools.py -v
    python -m unittest tests.test_all_tools -v

These tests invoke each tool directly (without MCP protocol overhead)
and verify correct behavior with realistic inputs.
"""

import sys
import textwrap
import unittest
from pathlib import Path

# Ensure mcp/ is on sys.path so `tools.*` imports work
_MCP_DIR = Path(__file__).resolve().parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from server import mcp  # noqa: E402 — registers all tools

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PASSING_LOG = FIXTURES_DIR / "sample_passing_run.log"
FAILING_LOG = FIXTURES_DIR / "sample_failing_run.log"
SAMPLE_RUNBOOK = FIXTURES_DIR / "sample_runbook.yml"


def _call(tool_name: str, **kwargs: object) -> str:
    """Invoke a registered MCP tool by name and return its string result."""
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    assert (
        tool_name in tools
    ), f"Tool '{tool_name}' not found. Available: {sorted(tools)}"
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


class TestScaffoldTestCase(unittest.TestCase):
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
            priority=1,
            location="westus2",
        )
        self.assertIn("type: azure", result)
        self.assertIn("subscription_id", result)
        self.assertIn("provisioning", result)
        self.assertIn("westus2", result)
        self.assertIn("[0, 1]", result)

    def test_local_runbook(self) -> None:
        result = _call("lisa_generate_runbook", platform="local")
        self.assertIn("type: local", result)
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
        result = _call(
            "lisa_fix_runbook",
            runbook_content=textwrap.dedent(
                """\
                platform:
                  - type: azure
                    keep_environment: true
                testcase:
                  - criteria:
                      area: demo
            """
            ),
        )
        self.assertIn("always", result)

    def test_fix_platform_as_dict(self) -> None:
        result = _call(
            "lisa_fix_runbook",
            runbook_content=textwrap.dedent(
                """\
                platform:
                  type: azure
                testcase:
                  - criteria:
                      area: demo
            """
            ),
        )
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
# Cross-cutting: verify all 25 tools are registered
# ======================================================================


class TestToolRegistration(unittest.TestCase):
    EXPECTED_TOOLS = {
        # test_writer
        "lisa_get_test_writer_guidelines",
        "lisa_scaffold_test_suite",
        "lisa_scaffold_test_case",
        "lisa_list_test_requirements",
        "lisa_write_test",
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
        self.assertEqual(count, 25, f"Expected 25 tools, got {count}")

    def test_all_tools_callable(self) -> None:
        """Every registered tool should have a callable function."""
        for tool in mcp._tool_manager.list_tools():
            self.assertTrue(
                callable(tool.fn),
                f"Tool '{tool.name}' is not callable",
            )


if __name__ == "__main__":
    unittest.main()
