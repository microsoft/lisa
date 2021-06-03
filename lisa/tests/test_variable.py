# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from pathlib import Path
from typing import Any, Dict, cast
from unittest.case import TestCase

from lisa import secret, variable
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger


class VariableTestCase(TestCase):
    def setUp(self) -> None:
        secret.reset()

    def test_in_env(self) -> None:
        os.environ["LISA_normal_value"] = "value_from_env"
        os.environ["S_LISA_normal_entry"] = "s_value_from_env"
        variables = self._get_default_variables()
        variables.update(variable._load_from_env())
        data = self._replace_and_validate(variables, {"normal_entry": "******"})
        self.assertEqual("value_from_env", data["nested"]["normal_value"])
        self.assertEqual("s_value_from_env", data["normal_entry"])

    def test_in_pair(self) -> None:
        pair1 = "normal_value:nv_from_pair"
        pair2 = "S:normal_entry:s_value_from_env"
        variables = self._get_default_variables()
        variables.update(variable.add_secrets_from_pairs([pair1, pair2]))
        data = self._replace_and_validate(variables, {"normal_entry": "******"})
        self.assertEqual("nv_from_pair", data["nested"]["normal_value"])
        self.assertEqual("s_value_from_env", data["normal_entry"])

    def test_in_normal_file_outside_secret(self) -> None:
        self._test_files(
            "variable_normal.yml",
            True,
            {
                "normal_value": "******",
                "normal_entry": "******",
                "secret_guid": "12345678-****-****-****-********90ab",
                "secret_int": "1****0",
                "secret_head_tail": "a****h",
            },
        )

    def test_in_normal_file(self) -> None:
        self._test_files(
            "variable_normal.yml",
            False,
            {
                "secret_guid": "12345678-****-****-****-********90ab",
                "secret_int": "1****0",
                "secret_head_tail": "a****h",
            },
        )

    def test_in_secret_file_outside_secret(self) -> None:
        self._test_files(
            "variable_secret.yml",
            True,
            {
                "normal_value": "******",
                "normal_entry": "******",
                "secret_guid": "12345678-****-****-****-********90ab",
                "secret_int": "1****0",
                "secret_head_tail": "a****h",
            },
        )

    def test_in_secret_file(self) -> None:
        self._test_files(
            "variable_secret.yml",
            False,
            {},
        )

    def test_in_runbook_format_file(self) -> None:
        runbook_data: Dict[str, Any] = {"variable": [{"file": "variable_normal.yml"}]}
        data = self._test_runbook_file_entry(
            runbook_data,
            {
                "secret_guid": "12345678-****-****-****-********90ab",
                "secret_int": "1****0",
                "secret_head_tail": "a****h",
            },
            {},
        )
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ab", data["list"][0])
        self.assertEqual(1234567890, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgh", data["headtail"])
        self.assertEqual("normal_value", data["nested"]["normal_value"])
        self.assertEqual("entry_value", data["normal_entry"])

    def test_in_variable_path_with_variable(self) -> None:
        runbook_data: Dict[str, Any] = {
            "variable": [
                {"file": "variable_$(var_in_var1).yml"},
                {"name": "var_in_var1", "value": "$(var_in_var2)"},
                {"name": "var_in_var2", "value": "normal"},
            ]
        }
        data = self._test_runbook_file_entry(
            runbook_data,
            {
                "secret_guid": "12345678-****-****-****-********90ab",
                "secret_int": "1****0",
                "secret_head_tail": "a****h",
            },
            {},
        )
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ab", data["list"][0])
        self.assertEqual(1234567890, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgh", data["headtail"])
        self.assertEqual("normal_value", data["nested"]["normal_value"])
        self.assertEqual("entry_value", data["normal_entry"])

    def test_in_runbook_path_with_variable(self) -> None:
        runbook_data: Dict[str, Any] = {
            "variable": [{"file": "variable_$(var_in_cmd).yml"}]
        }
        data = self._test_runbook_file_entry(
            runbook_data,
            {
                "secret_guid": "12345678-****-****-****-********90ab",
                "secret_int": "1****0",
                "secret_head_tail": "a****h",
            },
            {
                "var_in_cmd": variable.VariableEntry(
                    name="var_in_cmd", data="normal", is_used=False
                )
            },
        )
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ab", data["list"][0])
        self.assertEqual(1234567890, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgh", data["headtail"])
        self.assertEqual("normal_value", data["nested"]["normal_value"])
        self.assertEqual("entry_value", data["normal_entry"])

    def test_in_runbook_format_variable(self) -> None:
        runbook_data: Dict[str, Any] = {
            "variable": [
                {"name": "normal_value", "value": "normal_value"},
                {"name": "normal_entry", "value": {"value": "entry_value"}},
                {
                    "name": "secret_guid",
                    "value": {
                        "value": "12345678-abcd-efab-cdef-1234567890ab",
                        "is_secret": True,
                        "mask": "guid",
                    },
                },
                {
                    "name": "secret_int",
                    "value": {
                        "value": 1234567890,
                        "is_secret": True,
                        "mask": "headtail",
                    },
                },
                {
                    "name": "secret_head_tail",
                    "value": {
                        "value": "abcdefgh",
                        "is_secret": True,
                        "mask": "headtail",
                    },
                },
            ]
        }
        data = self._test_runbook_file_entry(
            runbook_data,
            {
                "secret_guid": "12345678-****-****-****-********90ab",
                "secret_int": "1****0",
                "secret_head_tail": "a****h",
            },
            {},
        )
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ab", data["list"][0])
        self.assertEqual(1234567890, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgh", data["headtail"])
        self.assertEqual("normal_value", data["nested"]["normal_value"])
        self.assertEqual("entry_value", data["normal_entry"])

    def test_in_runbook_ordered(self) -> None:
        runbook_data: Dict[str, Any] = {
            "variable": [
                {"file": "variable_normal.yml"},
                {"name": "normal_value", "value": "normal_value1"},
                {"name": "normal_entry", "value": {"value": "entry_value1"}},
                {
                    "name": "secret_guid",
                    "value": {
                        "value": "12345678-abcd-efab-cdef-1234567890ac",
                        "is_secret": True,
                        "mask": "guid",
                    },
                },
                {
                    "name": "secret_int",
                    "value": {
                        "value": 1234567891,
                        "is_secret": True,
                        "mask": "headtail",
                    },
                },
                {
                    "name": "secret_head_tail",
                    "value": {
                        "value": "abcdefgi",
                        "is_secret": True,
                        "mask": "headtail",
                    },
                },
            ]
        }
        data = self._test_runbook_file_entry(
            runbook_data,
            {
                "secret_guid": "12345678-****-****-****-********90ac",
                "secret_int": "1****1",
                "secret_head_tail": "a****i",
            },
            {},
        )
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ac", data["list"][0])
        self.assertEqual(1234567891, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgi", data["headtail"])
        self.assertEqual("normal_value1", data["nested"]["normal_value"])
        self.assertEqual("entry_value1", data["normal_entry"])

    def test_variable_not_found(self) -> None:
        variables = self._get_default_variables()
        with self.assertRaises(LisaException) as cm:
            variable.replace_variables({"item": "$(notexists)"}, variables)
        self.assertIsInstance(cm.exception, LisaException)
        self.assertIn("cannot find variable", str(cm.exception))

    def test_variable_not_used(self) -> None:
        variables = self._get_default_variables()
        variables["unused"] = variable.VariableEntry(name="unused", data="value")
        self.assertFalse(variables["unused"].is_used)
        self.assertFalse(variables["normal_value"].is_used)
        self._replace_and_validate(variables, {"normal_entry": "original"})
        self.assertFalse(variables["unused"].is_used)
        self.assertTrue(variables["normal_value"].is_used)

    def test_invalid_file_extension(self) -> None:
        variables = self._get_default_variables()
        with self.assertRaises(LisaException) as cm:
            variables.update(variable._load_from_file("file.xml"))
        self.assertIsInstance(cm.exception, LisaException)
        self.assertIn("variable support only yaml and yml", str(cm.exception))

    def _test_runbook_file_entry(
        self,
        data: Any,
        secret_variables: Dict[str, str],
        current_variables: Dict[str, variable.VariableEntry],
    ) -> Any:
        constants.RUNBOOK_PATH = Path(__file__).parent
        variables = self._get_default_variables()
        variables.update(variable._load_from_runbook(data, current_variables))
        data = self._replace_and_validate(variables, secret_variables)
        return data

    def _test_files(
        self, file_name: str, all_secret: bool, secret_variables: Dict[str, str]
    ) -> Any:
        constants.RUNBOOK_PATH = Path(__file__).parent
        variables = self._get_default_variables()
        variables.update(variable._load_from_file(file_name, is_secret=all_secret))
        data = self._replace_and_validate(variables, secret_variables)
        self.assertEqual("normal_value", data["nested"]["normal_value"])
        self.assertEqual("entry_value", data["normal_entry"])
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ab", data["list"][0])
        self.assertEqual(1234567890, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgh", data["headtail"])
        return data

    def _verify_secret(
        self, variables: Dict[str, variable.VariableEntry], secrets: Dict[str, str]
    ) -> None:
        log = get_logger()
        copied_variables = dict(variables)
        for secret_name, expected_value in secrets.items():
            secret_name = secret_name.lower()
            value = copied_variables[secret_name].data
            del copied_variables[secret_name]
            with self.assertLogs("lisa") as cm:
                log.info(f"MUST_SECRET[{value}]")
            self.assertListEqual(
                [f"INFO:lisa:MUST_SECRET[{expected_value}]"],
                cm.output,
                f"key: {secret_name}, value: {value}, "
                f"expected: {expected_value}  should be secret",
            )
        for key, unsecured_value in copied_variables.items():
            with self.assertLogs("lisa") as cm:
                log.info(f"MUST_NOT_SECRET[{unsecured_value}]")
            self.assertListEqual(
                [f"INFO:lisa:MUST_NOT_SECRET[{unsecured_value}]"],
                cm.output,
                f"key: {key}, value: {unsecured_value} shouldn't be secret",
            )

    def _get_default_variables(self) -> Dict[str, variable.VariableEntry]:
        data = {
            "normal_value": variable.VariableEntry("normal_value", "original"),
            "normal_entry": variable.VariableEntry("normal_entry", "original"),
            "secret_guid": variable.VariableEntry("secret_guid", "original"),
            "secret_int": variable.VariableEntry("secret_int", "original"),
            "secret_head_tail": variable.VariableEntry("secret_head_tail", "original"),
        }
        return data

    def _replace_and_validate(
        self, variables: Dict[str, variable.VariableEntry], secrets: Dict[str, str]
    ) -> Dict[str, Any]:
        data = variable.replace_variables(self._get_default_data(), variables=variables)
        assert isinstance(data, dict), f"actual: {type(data)}"
        self.assertDictEqual(
            {
                "keep": "normal",
                "normal_entry": variables["normal_entry"].data,
                "headtail": variables["secret_head_tail"].data,
                "nested": {"normal_value": variables["normal_value"].data},
                "list": [
                    variables["secret_guid"].data,
                    {"dictInList": variables["secret_int"].data},
                ],
                "two_entries": f"1{variables['normal_entry'].data}"
                f"2-$-()3{variables['normal_entry'].data}4",
            },
            data,
        )
        self._verify_secret(variables, secrets=secrets)
        data = cast(Dict[str, Any], data)
        return data

    def _get_default_data(self) -> Dict[str, Any]:
        data = {
            "keep": "normal",
            "normal_entry": "$(normal_entry)",
            "headtail": "$(secret_head_tail)",
            "nested": {"normal_value": "$(normal_value)"},
            "list": ["$(secret_guid)", {"dictInList": "$(secret_int)"}],
            "two_entries": "1$(normal_entry)2-$-()3$(normal_entry)4",
        }
        return data
