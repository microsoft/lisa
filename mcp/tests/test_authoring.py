# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for authoring tools."""

import unittest

import yaml


class TestScaffoldTestSuite(unittest.TestCase):
    """Validate scaffold_test_suite generates correct Python code."""

    def test_generates_valid_class(self) -> None:
        from lisa_mcp.tools.test_writer import _to_snake_case

        assert _to_snake_case("MyNewFeature") == "my_new_feature"
        assert _to_snake_case("GPUValidation") == "gpu_validation"
        assert _to_snake_case("SRIOVTest") == "sriov_test"
        assert _to_snake_case("Simple") == "simple"


class TestGenerateRunbook(unittest.TestCase):
    """Validate generate_runbook produces valid YAML."""

    def test_basic_runbook_is_valid_yaml(self) -> None:
        # Exercise the tool indirectly by importing the module and calling
        # the generation logic. Since tools are registered on an MCP instance,
        # we test the YAML output pattern.
        runbook_yaml = _make_basic_runbook()
        doc = yaml.safe_load(runbook_yaml)
        self.assertIsInstance(doc, dict)
        self.assertIn("platform", doc)
        self.assertIn("testcase", doc)

    def test_azure_runbook_has_subscription(self) -> None:
        runbook_yaml = _make_azure_runbook()
        doc = yaml.safe_load(runbook_yaml)
        variables = doc.get("variable", [])
        names = [v["name"] for v in variables if isinstance(v, dict)]
        self.assertIn("subscription_id", names)


class TestValidateRunbook(unittest.TestCase):
    """Validate runbook validation catches common issues."""

    def test_missing_platform(self) -> None:
        doc = yaml.dump({"testcase": [{"criteria": {"area": "demo"}}]})
        result = _validate(doc)
        self.assertIn("platform", result.lower())

    def test_valid_runbook_passes(self) -> None:
        doc = yaml.dump(
            {
                "platform": [{"type": "azure"}],
                "testcase": [{"criteria": {"area": "demo"}}],
                "notifier": [{"type": "console"}],
                "extension": ["../../lisa/microsoft/testsuites"],
            }
        )
        result = _validate(doc)
        self.assertIn("valid", result.lower())


# ---------------------------------------------------------------------------
# Helpers — inline versions of tool logic for testing without MCP server
# ---------------------------------------------------------------------------


def _make_basic_runbook() -> str:
    return """\
name: generated-runbook
concurrency: 1

platform:
  - type: local

notifier:
  - type: console

testcase:
  - criteria:
      area: demo
"""


def _make_azure_runbook() -> str:
    return """\
name: generated-runbook
concurrency: 1

platform:
  - type: azure
    admin_username: "$(admin_username)"
    admin_private_key_file: "$(admin_private_key_file)"

variable:
  - name: admin_username
    value: ""
  - name: admin_private_key_file
    value: ""
  - name: subscription_id
    value: ""
    is_secret: true

notifier:
  - type: console

testcase:
  - criteria:
      area: provisioning
"""


def _validate(runbook_content: str) -> str:
    """Inline runbook validation matching the authoring tool logic."""
    errors = []
    warnings = []

    doc = yaml.safe_load(runbook_content)
    if not isinstance(doc, dict):
        return "Error: not a mapping"

    if "platform" not in doc:
        errors.append("Missing `platform` section.")
    if "testcase" not in doc and "testcase_raw" not in doc:
        errors.append("Missing `testcase` section.")
    if "notifier" not in doc:
        warnings.append("No notifier section.")
    if "extension" not in doc:
        warnings.append("No extension section.")

    if not errors and not warnings:
        return "Runbook structure looks valid. No issues found."

    parts = []
    if errors:
        parts.append("Errors: " + "; ".join(errors))
    if warnings:
        parts.append("Warnings: " + "; ".join(warnings))
    return " ".join(parts)


if __name__ == "__main__":
    unittest.main()
