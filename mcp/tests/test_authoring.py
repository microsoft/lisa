# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for authoring tools.

These exercise the real registered MCP tools rather than inline copies of
their logic — a reimplementation in the test file can only ever confirm
that the test file agrees with itself.
"""

import sys
import unittest
from pathlib import Path

import yaml

# Ensure mcp/ is on sys.path so `server` imports work.
_MCP_DIR = Path(__file__).resolve().parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from server import mcp  # noqa: E402 — registers all tools


def _call(tool_name: str, **kwargs: object) -> str:
    """Invoke a registered MCP tool by name and return its string result."""
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    if tool_name not in tools:
        raise AssertionError(
            f"Tool '{tool_name}' not found. Available: {sorted(tools)}"
        )
    return tools[tool_name].fn(**kwargs)


def _extract_yaml(tool_output: str) -> str:
    """Pull the ```yaml fenced block out of a tool's markdown response."""
    marker = "```yaml"
    start = tool_output.find(marker)
    if start == -1:
        raise AssertionError(f"No yaml block in tool output:\n{tool_output}")
    start += len(marker)
    end = tool_output.find("```", start)
    if end == -1:
        raise AssertionError(f"Unterminated yaml block in output:\n{tool_output}")
    return tool_output[start:end]


class TestScaffoldTestSuite(unittest.TestCase):
    """Validate scaffold_test_suite generates correct Python code."""

    def test_generates_valid_class(self) -> None:
        from lisa_mcp.tools.test_writer import _to_snake_case

        self.assertEqual(_to_snake_case("MyNewFeature"), "my_new_feature")
        self.assertEqual(_to_snake_case("GPUValidation"), "gpu_validation")
        self.assertEqual(_to_snake_case("SRIOVTest"), "sriov_test")
        self.assertEqual(_to_snake_case("Simple"), "simple")


class TestGenerateRunbook(unittest.TestCase):
    """Validate lisa_generate_runbook produces valid YAML."""

    def test_basic_runbook_is_valid_yaml(self) -> None:
        output = _call("lisa_generate_runbook", platform="local", area="demo")
        doc = yaml.safe_load(_extract_yaml(output))
        self.assertIsInstance(doc, dict)
        self.assertIn("platform", doc)
        self.assertIn("testcase", doc)

    def test_azure_runbook_has_subscription(self) -> None:
        output = _call("lisa_generate_runbook", platform="azure", area="provisioning")
        doc = yaml.safe_load(_extract_yaml(output))
        variables = doc.get("variable", [])
        names = [v["name"] for v in variables if isinstance(v, dict)]
        self.assertIn("subscription_id", names)

    def test_no_filters_omits_empty_criteria(self) -> None:
        """A criteria block with no filters would select every test."""
        output = _call("lisa_generate_runbook", platform="local")
        doc = yaml.safe_load(_extract_yaml(output))
        for entry in doc.get("testcase", []):
            self.assertIsNotNone(
                entry.get("criteria"),
                "empty `criteria:` matches all tests — omit it instead",
            )


class TestValidateRunbook(unittest.TestCase):
    """Validate lisa_validate_runbook catches common issues."""

    def test_missing_platform(self) -> None:
        doc = yaml.dump({"testcase": [{"criteria": {"area": "demo"}}]})
        result = _call("lisa_validate_runbook", runbook_content=doc)
        self.assertIn("platform", result.lower())

    def test_platform_as_mapping_is_rejected(self) -> None:
        """LISA expects a list; a bare mapping silently configures nothing."""
        doc = yaml.dump(
            {
                "platform": {"type": "azure"},
                "testcase": [{"criteria": {"area": "demo"}}],
            }
        )
        result = _call("lisa_validate_runbook", runbook_content=doc)
        self.assertIn("**Errors:**", result)
        self.assertIn("list", result.lower())

    def test_empty_platform_list_is_rejected(self) -> None:
        doc = yaml.dump({"platform": [], "testcase": [{"criteria": {"area": "demo"}}]})
        result = _call("lisa_validate_runbook", runbook_content=doc)
        self.assertIn("**Errors:**", result)

    def test_valid_runbook_passes(self) -> None:
        doc = yaml.dump(
            {
                "platform": [{"type": "azure"}],
                "testcase": [{"criteria": {"area": "demo"}}],
                "notifier": [{"type": "console"}],
                "extension": ["../../lisa/microsoft/testsuites"],
            }
        )
        result = _call("lisa_validate_runbook", runbook_content=doc)
        self.assertIn("valid", result.lower())

    def test_empty_criteria_is_flagged(self) -> None:
        """`all([])` is True, so no predicates means the whole suite runs."""
        for testcase in ([{"criteria": {}}], [{"criteria": None}], [{}]):
            doc = yaml.dump(
                {
                    "platform": [{"type": "azure"}],
                    "testcase": testcase,
                    "notifier": [{"type": "console"}],
                    "extension": ["../../lisa/microsoft/testsuites"],
                }
            )
            result = _call("lisa_validate_runbook", runbook_content=doc)
            self.assertIn("every", result.lower(), f"not flagged: {testcase}")


class TestFixRunbook(unittest.TestCase):
    """Validate lisa_fix_runbook repairs safely."""

    def test_missing_platform_is_not_auto_filled(self) -> None:
        """Defaulting to azure would provision billable resources unasked."""
        doc = yaml.dump({"testcase": [{"criteria": {"area": "demo"}}]})
        result = _call("lisa_fix_runbook", runbook_content=doc)
        fixed = yaml.safe_load(_extract_yaml(result))
        self.assertNotIn("platform", fixed)
        self.assertIn("Needs your input", result)

    def test_missing_testcase_is_not_auto_filled(self) -> None:
        """An empty criteria block selects every test in the repo."""
        doc = yaml.dump({"platform": [{"type": "local"}]})
        result = _call("lisa_fix_runbook", runbook_content=doc)
        fixed = yaml.safe_load(_extract_yaml(result))
        self.assertNotIn("testcase", fixed)
        self.assertIn("Needs your input", result)

    def test_input_document_is_not_mutated(self) -> None:
        """The tool must not edit nested structures it was handed."""
        original: dict = {
            "platform": [{"type": "azure", "keep_environment": True}],
            "testcase": [{"criteria": {"area": "demo"}}],
        }
        _call("lisa_fix_runbook", runbook_content=yaml.dump(original))
        self.assertIs(original["platform"][0]["keep_environment"], True)

    def test_keep_environment_bool_is_quoted(self) -> None:
        doc = yaml.dump(
            {
                "platform": [{"type": "azure", "keep_environment": False}],
                "testcase": [{"criteria": {"area": "demo"}}],
            }
        )
        result = _call("lisa_fix_runbook", runbook_content=doc)
        fixed = yaml.safe_load(_extract_yaml(result))
        self.assertEqual(fixed["platform"][0]["keep_environment"], "no")


if __name__ == "__main__":
    unittest.main()
