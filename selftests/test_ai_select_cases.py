# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "ai_select_cases", _REPO_ROOT / ".github" / "scripts" / "ai_select_cases.py"
)
assert _SPEC is not None and _SPEC.loader is not None
selector = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(selector)


class ToolCaseMappingTestCase(TestCase):
    def test_hibernation_selection_writes_targeted_runbook(self) -> None:
        case_name = "verify_hibernation_synthetic_network"
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "selected.yml"
            github_output = Path(temp_dir) / "github_output"
            env = {
                "PR_CHANGED_FILES": "lisa/tools/hibernation_setup.py",
                "RUNBOOK_OUTPUT": str(output_path),
                "GITHUB_OUTPUT": str(github_output),
                "AZURE_OPENAI_API_KEY": "test-key",
                "AZURE_OPENAI_ENDPOINT": "https://example.invalid",
            }
            with patch.dict(os.environ, env, clear=True), patch.object(
                selector, "select_with_model", return_value=f'["{case_name}"]'
            ) as select_model:
                selector.main()
            select_model.assert_called_once()
            self.assertIn(case_name, output_path.read_text(encoding="utf-8"))
            outputs = github_output.read_text(encoding="utf-8")
            self.assertIn("case_count=1\n", outputs)
            self.assertIn(f"case_names={case_name}\n", outputs)
            self.assertNotIn("smoke_test", outputs)

    def test_hibernation_change_has_targeted_candidates(self) -> None:
        all_cases = selector.list_test_cases(
            _REPO_ROOT,
            _REPO_ROOT / "lisa" / "microsoft" / "testsuites" / "power",
        )
        known_tools = {tool for _, _, _, _, _, tools in all_cases for tool in tools}
        changed_file = "lisa/tools/hibernation_setup.py"
        changed_tools = selector.extract_changed_tool_names(
            _REPO_ROOT, changed_file, "", known_tools
        )
        self.assertIn("HibernationSetup", changed_tools)
        related_cases = selector.get_tool_related_cases(all_cases, changed_tools)
        self.assertIn("verify_hibernation_synthetic_network", related_cases)
        candidates = selector.select_candidate_cases(
            all_cases, [], [], related_cases, changed_file, "", (), changed_tools, 120
        )
        self.assertIn("verify_hibernation_synthetic_network", candidates)
        self.assertNotIn("smoke_test", candidates)

    def test_direct_tool_usage_is_preserved(self) -> None:
        cases = [
            ("suite.py", "power", "direct_case", 1, (), ("Date",)),
            ("suite.py", "power", "unrelated_case", 1, (), ()),
        ]
        self.assertEqual(
            ["direct_case"], selector.get_tool_related_cases(cases, ("Date",))
        )

    def test_mapping_does_not_invent_cases(self) -> None:
        cases = [("suite.py", "power", "unrelated_case", 1, (), ())]
        self.assertEqual(
            [], selector.get_tool_related_cases(cases, ("HibernationSetup",))
        )

    def test_direct_and_mapped_usage_is_not_duplicated(self) -> None:
        case_name = "verify_hibernation_synthetic_network"
        cases = [("power.py", "power", case_name, 3, (), ("HibernationSetup",))]
        self.assertEqual(
            [case_name],
            selector.get_tool_related_cases(cases, ("HibernationSetup",)),
        )

    def test_unrelated_tool_does_not_select_hibernation(self) -> None:
        cases = [
            ("power.py", "power", "verify_hibernation_synthetic_network", 3, (), ())
        ]
        self.assertEqual([], selector.get_tool_related_cases(cases, ("Unknown",)))
        self.assertEqual([], selector.get_tool_related_cases(cases, ()))
