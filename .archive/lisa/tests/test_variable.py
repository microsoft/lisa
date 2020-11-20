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
        os.environ["LISA_normalValue"] = "value_from_env"
        os.environ["S_LISA_normalEntry"] = "s_value_from_env"
        variables = self._get_default_variables()
        variable.load_from_env(variables)
        data = self._replace_and_validate(variables, {"normalEntry": "******"})
        self.assertEqual("value_from_env", data["nested"]["normal_value"])
        self.assertEqual("s_value_from_env", data["normalEntry"])

    def test_in_pair(self) -> None:
        pair1 = "normalValue:nv_from_pair"
        pair2 = "S:normalEntry:s_value_from_env"
        variables = self._get_default_variables()
        variable.load_from_pairs([pair1, pair2], variables)
        data = self._replace_and_validate(variables, {"normalEntry": "******"})
        self.assertEqual("nv_from_pair", data["nested"]["normal_value"])
        self.assertEqual("s_value_from_env", data["normalEntry"])

    def test_in_normal_file_outside_secret(self) -> None:
        self._test_files(
            "variable_normal.yml",
            True,
            {
                "normalValue": "******",
                "normalEntry": "******",
                "secretGuid": "12345678-****-****-****-********90ab",
                "secretInt": "1****0",
                "secretHeadTail": "a****h",
            },
        )

    def test_in_normal_file(self) -> None:
        self._test_files(
            "variable_normal.yml",
            False,
            {
                "secretGuid": "12345678-****-****-****-********90ab",
                "secretInt": "1****0",
                "secretHeadTail": "a****h",
            },
        )

    def test_in_secret_file_outside_secret(self) -> None:
        self._test_files(
            "variable_secret.yml",
            True,
            {
                "normalValue": "******",
                "normalEntry": "******",
                "secretGuid": "12345678-****-****-****-********90ab",
                "secretInt": "1****0",
                "secretHeadTail": "a****h",
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
                "secretGuid": "12345678-****-****-****-********90ab",
                "secretInt": "1****0",
                "secretHeadTail": "a****h",
            },
        )
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ab", data["list"][0])
        self.assertEqual(1234567890, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgh", data["headtail"])
        self.assertEqual("normal_value", data["nested"]["normal_value"])
        self.assertEqual("entry_value", data["normalEntry"])

    def test_in_runbook_format_variable(self) -> None:
        runbook_data: Dict[str, Any] = {
            "variable": [
                {"name": "normalValue", "value": "normal_value"},
                {"name": "normalEntry", "value": {"value": "entry_value"}},
                {
                    "name": "secretGuid",
                    "value": {
                        "value": "12345678-abcd-efab-cdef-1234567890ab",
                        "isSecret": True,
                        "mask": "guid",
                    },
                },
                {
                    "name": "secretInt",
                    "value": {
                        "value": 1234567890,
                        "isSecret": True,
                        "mask": "headtail",
                    },
                },
                {
                    "name": "secretHeadTail",
                    "value": {
                        "value": "abcdefgh",
                        "isSecret": True,
                        "mask": "headtail",
                    },
                },
            ]
        }
        data = self._test_runbook_file_entry(
            runbook_data,
            {
                "secretGuid": "12345678-****-****-****-********90ab",
                "secretInt": "1****0",
                "secretHeadTail": "a****h",
            },
        )
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ab", data["list"][0])
        self.assertEqual(1234567890, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgh", data["headtail"])
        self.assertEqual("normal_value", data["nested"]["normal_value"])
        self.assertEqual("entry_value", data["normalEntry"])

    def test_in_runbook_ordered(self) -> None:
        runbook_data: Dict[str, Any] = {
            "variable": [
                {"file": "variable_normal.yml"},
                {"name": "normalValue", "value": "normal_value1"},
                {"name": "normalEntry", "value": {"value": "entry_value1"}},
                {
                    "name": "secretGuid",
                    "value": {
                        "value": "12345678-abcd-efab-cdef-1234567890ac",
                        "isSecret": True,
                        "mask": "guid",
                    },
                },
                {
                    "name": "secretInt",
                    "value": {
                        "value": 1234567891,
                        "isSecret": True,
                        "mask": "headtail",
                    },
                },
                {
                    "name": "secretHeadTail",
                    "value": {
                        "value": "abcdefgi",
                        "isSecret": True,
                        "mask": "headtail",
                    },
                },
            ]
        }
        data = self._test_runbook_file_entry(
            runbook_data,
            {
                "secretGuid": "12345678-****-****-****-********90ac",
                "secretInt": "1****1",
                "secretHeadTail": "a****i",
            },
        )
        self.assertEqual("12345678-abcd-efab-cdef-1234567890ac", data["list"][0])
        self.assertEqual(1234567891, data["list"][1]["dictInList"])
        self.assertEqual("abcdefgi", data["headtail"])
        self.assertEqual("normal_value1", data["nested"]["normal_value"])
        self.assertEqual("entry_value1", data["normalEntry"])

    def test_variable_not_found(self) -> None:
        variables = self._get_default_variables()
        with self.assertRaises(LisaException) as cm:
            variable.replace_variables({"item": "$(notexists)"}, variables)
        self.assertIsInstance(cm.exception, LisaException)
        self.assertIn("cannot find variable", str(cm.exception))

    def test_variable_not_used(self) -> None:
        variables = self._get_default_variables()
        variables["unused"] = variable.VariableEntry("value")
        self.assertFalse(variables["unused"].is_used)
        self.assertFalse(variables["normalvalue"].is_used)
        self._replace_and_validate(variables, {"normalEntry": "original"})
        self.assertFalse(variables["unused"].is_used)
        self.assertTrue(variables["normalvalue"].is_used)

    def test_invalid_file_extension(self) -> None:
        variables = self._get_default_variables()
        with self.assertRaises(LisaException) as cm:
            variable.load_from_file("file.xml", variables)
        self.assertIsInstance(cm.exception, LisaException)
        self.assertIn("variable support only yaml and yml", str(cm.exception))

    def _test_runbook_file_entry(
        self, data: Any, secret_variables: Dict[str, str]
    ) -> Any:
        constants.RUNBOOK_PATH = Path(__file__).parent
        variables = self._get_default_variables()
        variable.load_from_runbook(data, variables)
        data = self._replace_and_validate(variables, secret_variables)
        return data

    def _test_files(
        self, file_name: str, all_secret: bool, secret_variables: Dict[str, str]
    ) -> Any:
        constants.RUNBOOK_PATH = Path(__file__).parent
        variables = self._get_default_variables()
        variable.load_from_file(file_name, variables, is_secret=all_secret)
        data = self._replace_and_validate(variables, secret_variables)
        self.assertEqual("normal_value", data["nested"]["normal_value"])
        self.assertEqual("entry_value", data["normalEntry"])
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
            with self.assertLogs("LISA") as cm:
                log.info(f"MUST_SECRET[{value}]")
            self.assertListEqual(
                [f"INFO:LISA:MUST_SECRET[{expected_value}]"],
                cm.output,
                f"key: {secret_name}, value: {value}, "
                f"expected: {expected_value}  should be secret",
            )
        for key, unsecret_value in copied_variables.items():
            with self.assertLogs("LISA") as cm:
                log.info(f"MUST_NOT_SECRET[{unsecret_value}]")
            self.assertListEqual(
                [f"INFO:LISA:MUST_NOT_SECRET[{unsecret_value}]"],
                cm.output,
                f"key: {key}, value: {unsecret_value} shouldn't be secret",
            )

    def _get_default_variables(self) -> Dict[str, variable.VariableEntry]:
        data = {
            "normalvalue": variable.VariableEntry("original"),
            "normalentry": variable.VariableEntry("original"),
            "secretguid": variable.VariableEntry("original"),
            "secretint": variable.VariableEntry("original"),
            "secretheadtail": variable.VariableEntry("original"),
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
                "normalEntry": variables["normalentry"].data,
                "headtail": variables["secretheadtail"].data,
                "nested": {"normal_value": variables["normalvalue"].data},
                "list": [
                    variables["secretguid"].data,
                    {"dictInList": variables["secretint"].data},
                ],
            },
            data,
        )
        self._verify_secret(variables, secrets=secrets)
        data = cast(Dict[str, Any], data)
        return data

    def _get_default_data(self) -> Dict[str, Any]:
        data = {
            "keep": "normal",
            "normalEntry": "$(normalEntry)",
            "headtail": "$(secretHeadTail)",
            "nested": {"normal_value": "$(normalValue)"},
            "list": ["$(secretGuid)", {"dictInList": "$(secretInt)"}],
        }
        return data
