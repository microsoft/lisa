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
        self.assertIn("resource_group_name", names)

    def test_local_becomes_a_ready_platform_with_a_node(self) -> None:
        """`local` is a node type; the platform factory cannot load it."""
        output = _call("lisa_generate_runbook", platform="local", area="demo")
        doc = yaml.safe_load(_extract_yaml(output))
        self.assertEqual([p["type"] for p in doc["platform"]], ["ready"])
        nodes = doc["environment"]["environments"][0]["nodes"]
        self.assertEqual([n["type"] for n in nodes], ["local"])

    def test_remote_becomes_a_ready_platform_with_a_node(self) -> None:
        output = _call("lisa_generate_runbook", platform="remote", area="demo")
        doc = yaml.safe_load(_extract_yaml(output))
        self.assertEqual([p["type"] for p in doc["platform"]], ["ready"])
        node = doc["environment"]["environments"][0]["nodes"][0]
        self.assertEqual(node["type"], "remote")
        self.assertIn("address", node)

    def test_azure_options_sit_under_platform_requirement(self) -> None:
        """location/vm_size/marketplace are node requirements, not platform
        settings — see lisa/microsoft/runbook/azure.yml."""
        output = _call(
            "lisa_generate_runbook",
            platform="azure",
            area="demo",
            location="westus2",
            vm_size="Standard_DS2_v2",
            image="canonical ubuntu-24_04-lts server latest",
        )
        doc = yaml.safe_load(_extract_yaml(output))
        entry = doc["platform"][0]
        requirement = entry["requirement"]["azure"]
        self.assertEqual(requirement["location"], "westus2")
        self.assertEqual(requirement["vm_size"], "Standard_DS2_v2")
        self.assertEqual(requirement["marketplace"]["publisher"], "canonical")
        # The platform node itself only carries connection settings.
        self.assertNotIn("requirement", entry["azure"])
        self.assertNotIn("deploy_location", entry["azure"])

    def test_no_filters_omits_empty_criteria(self) -> None:
        """A criteria block with no filters would select every test."""
        output = _call("lisa_generate_runbook", platform="local")
        doc = yaml.safe_load(_extract_yaml(output))
        for entry in doc.get("testcase", []):
            self.assertIsNotNone(
                entry.get("criteria"),
                "empty `criteria:` matches all tests — omit it instead",
            )

    def test_hostile_values_cannot_restructure_the_yaml(self) -> None:
        """Interpolated scalars must not be able to inject YAML nodes."""
        payloads = [
            "demo: injected",
            "demo\nplatform:\n  - type: azure",
            'demo"quote',
            "demo\\back",
            "*anchor",
            "!!python/object/apply:os.system",
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                output = _call("lisa_generate_runbook", platform="ready", area=payload)
                doc = yaml.safe_load(_extract_yaml(output))
                self.assertEqual([p["type"] for p in doc["platform"]], ["ready"])
                self.assertEqual(doc["testcase"][0]["criteria"]["area"], payload)

    def test_hostile_tags_and_names_are_quoted(self) -> None:
        output = _call(
            "lisa_generate_runbook",
            platform="ready",
            tags="good, bad: value",
            test_names="verify_ok, evil: name",
        )
        doc = yaml.safe_load(_extract_yaml(output))
        criteria = doc["testcase"]
        self.assertIn("bad: value", criteria[0]["criteria"]["tags"])
        self.assertEqual(criteria[-1]["criteria"]["name"], "evil: name")

    def test_invalid_enum_and_numeric_inputs_are_rejected(self) -> None:
        cases = [
            {"platform": "not-a-platform"},
            {"platform": "ready", "keep_environment": "maybe"},
            {"platform": "ready", "concurrency": 0},
            {"platform": "ready", "max_priority": -1},
            {"platform": "ready", "image": "too few fields"},
        ]
        for kwargs in cases:
            with self.subTest(**kwargs):
                result = _call("lisa_generate_runbook", **kwargs)
                self.assertIn("**Error:**", result)
                self.assertNotIn("```yaml", result)

    def test_stress_priorities_are_selectable(self) -> None:
        """LISA suites use priority 4 and 5; the generator must reach them."""
        for level in (3, 4, 5):
            with self.subTest(level=level):
                output = _call(
                    "lisa_generate_runbook", platform="ready", max_priority=level
                )
                doc = yaml.safe_load(_extract_yaml(output))
                self.assertEqual(doc["testcase"][0]["criteria"]["priority"], [0, level])


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

    def test_testcase_as_mapping_is_rejected(self) -> None:
        """LISA expects a list; a mapping used to pass validation silently."""
        doc = yaml.dump(
            {
                "platform": [{"type": "azure"}],
                "testcase": {"criteria": {"area": "demo"}},
            }
        )
        result = _call("lisa_validate_runbook", runbook_content=doc)
        self.assertIn("**Errors:**", result)
        self.assertIn("list", result.lower())

    def test_node_type_used_as_platform_is_rejected(self) -> None:
        """`platform: local` produces a runbook the factory cannot load."""
        for node_type in ("local", "remote"):
            doc = yaml.dump(
                {
                    "platform": [{"type": node_type}],
                    "testcase": [{"criteria": {"area": "demo"}}],
                }
            )
            result = _call("lisa_validate_runbook", runbook_content=doc)
            self.assertIn("**Errors:**", result, node_type)
            self.assertIn("ready", result, node_type)

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
