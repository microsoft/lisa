# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from pathlib import Path
from typing import Any, Iterator
from unittest import TestCase


def _iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested_value in value.values():
            yield from _iter_strings(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            yield from _iter_strings(nested_value)


class AzureArmTemplateTestCase(TestCase):
    def test_optional_cvm_vhd_properties_use_safe_access(self) -> None:
        template_path = (
            Path(__file__).resolve().parents[2]
            / "lisa"
            / "sut_orchestrator"
            / "azure"
            / "autogen_arm_template.json"
        )
        with template_path.open(encoding="utf-8") as template_file:
            template = json.load(template_file)

        cvm_property_expressions = [
            value
            for value in _iter_strings(template)
            if "cvm_gueststate_path" in value or "cvm_metadata_path" in value
        ]

        self.assertTrue(cvm_property_expressions)
        for expression in cvm_property_expressions:
            self.assertIn("tryGet(", expression)
