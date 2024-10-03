# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Type
from unittest import TestCase

import yaml
from dataclasses_json import dataclass_json

from lisa import LisaException, constants, schema, transformer
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.transformer import Transformer
from lisa.variable import VariableEntry

MOCK = "mock"


@dataclass_json
@dataclass
class TestTransformerSchema(schema.Transformer):
    items: Dict[str, str] = field(default_factory=dict)


class TestTransformer(Transformer):
    """
    This transformer transfer string to a list, so the combinator can use it.
    """

    @classmethod
    def type_name(cls) -> str:
        return MOCK

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return TestTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        runbook: TestTransformerSchema = self.runbook
        return [x for x in runbook.items]

    def _internal_run(self) -> Dict[str, Any]:
        runbook: TestTransformerSchema = self.runbook
        result: Dict[str, Any] = dict()
        for name, value in runbook.items.items():
            result[name] = f"{value} processed"

        return result


class TestTransformerCase(TestCase):
    def test_transformer_ordered(self) -> None:
        # transformers are sorted by the dependent order
        transformers = self._generate_transformers_runbook(3)
        transformers[0].depends_on = ["t1", "t2"]
        transformers[1].depends_on = ["t2"]

        transformers = transformer._sort(transformers)
        self.assertEqual("t2", transformers[0].name)
        self.assertEqual("t1", transformers[1].name)
        self.assertEqual("t0", transformers[2].name)

    def test_transformer_cycle_detection(self) -> None:
        # cycle reference and raise exception
        transformers = self._generate_transformers_runbook(3)
        transformers[0].depends_on = ["t1", "t2"]
        transformers[1].depends_on = ["t0"]

        with self.assertRaises(LisaException) as cm:
            transformers = transformer._sort(transformers)
        self.assertEqual(
            "found cycle dependent transformers: 't1' and 't0'", str(cm.exception)
        )

    def test_transformer_keep_all_values(self) -> None:
        # no value is overridden, all values are kept
        transformers = self._generate_transformers_runbook(2)
        runbook_builder = self._generate_runbook_builder(transformers)

        result = transformer._run_transformers(runbook_builder)
        self._validate_variables(
            {
                "v0": "original",
                "va": "original",
                "t0_v0": "0_0 processed",
                "t1_v0": "1_0 processed",
                "t1_v1": "1_1 processed",
            },
            result,
        )

    def test_transformer_overridden_values(self) -> None:
        # value is overridden
        transformers = self._generate_transformers_runbook(2)
        transformers[0].rename = {"t0_v0": "v0"}
        transformers[1].rename = {"t1_v0": "v0", "t1_v1": "v1"}
        runbook_builder = self._generate_runbook_builder(transformers)

        result = transformer._run_transformers(runbook_builder)
        self._validate_variables(
            {
                "va": "original",
                "v0": "1_0 processed",
                "v1": "1_1 processed",
            },
            result,
        )

    def test_transformer_rename_not_exist(self) -> None:
        # not exist name raise exception
        transformers = self._generate_transformers_runbook(1)
        transformers[0].rename = {"v0": "v0_1"}
        runbook_builder = self._generate_runbook_builder(transformers)

        with self.assertRaises(LisaException) as cm:
            transformer._run_transformers(runbook_builder)
        self.assertEqual("unmatched rename variable: {'v0': 'v0_1'}", str(cm.exception))

    def test_transformer_customized_prefix(self) -> None:
        # modified prefix
        transformers = self._generate_transformers_runbook(1)
        transformers[0].prefix = "v0_1"
        runbook_builder = self._generate_runbook_builder(transformers)

        result = transformer._run_transformers(runbook_builder)
        self._validate_variables(
            {
                "v0": "original",
                "va": "original",
                "v0_1_v0": "0_0 processed",
            },
            result,
        )

    def test_transformer_no_name(self) -> None:
        # no name, the type will be used. in name
        transformers_data: List[Any] = [{"type": MOCK, "items": {"v0": "v0_1"}}]
        transformers = schema.load_by_type_many(schema.Transformer, transformers_data)
        runbook_builder = self._generate_runbook_builder(transformers)

        result = transformer._run_transformers(runbook_builder)
        self._validate_variables(
            {
                "v0": "original",
                "va": "original",
                "mock_v0": "v0_1 processed",
            },
            result,
        )

    def test_transformer_skip_disabled(self) -> None:
        # the second transformer should be skipped, so the value is original.
        transformers = self._generate_transformers_runbook(2)
        transformers[0].rename = {"t0_v0": "v0"}
        transformers[0].enabled = False
        runbook_builder = self._generate_runbook_builder(transformers)

        result = transformer._run_transformers(runbook_builder)
        self._validate_variables(
            {
                "v0": "original",
                "va": "original",
                "t1_v0": "1_0 processed",
                "t1_v1": "1_1 processed",
            },
            result,
        )

    def _validate_variables(
        self, expected: Dict[str, str], actual: Dict[str, VariableEntry]
    ) -> None:
        actual_pairs = {name: value.data for name, value in actual.items()}
        self.assertDictEqual(expected, actual_pairs)

    def _generate_runbook_builder(
        self, transformers: List[schema.Transformer]
    ) -> RunbookBuilder:
        transformers_data: List[Any] = [
            x.to_dict() for x in transformers  # type:ignore
        ]
        test_runbook_path = Path(__file__).parent / "test_runbook.yml"

        runbook_builder = RunbookBuilder(test_runbook_path)
        runbook_builder._raw_data = {
            constants.TRANSFORMER: transformers_data,
        }
        runbook_builder._variables = {
            "v0": VariableEntry("v0", "original"),
            "va": VariableEntry("va", "original"),
        }

        # write to file for reloading in runbook.derive method.
        with open(test_runbook_path, "w") as file:
            yaml.dump(runbook_builder._raw_data, file)
        return runbook_builder

    def _generate_transformers_runbook(self, count: int) -> List[schema.Transformer]:
        results: List[schema.Transformer] = []
        for index in range(count):
            items: Dict[str, str] = dict()
            for item_index in range(index + 1):
                items[f"v{item_index}"] = f"{index}_{item_index}"
            runbook: schema.Transformer = schema.load_by_type(
                schema.Transformer, {"type": MOCK, "name": f"t{index}", "items": items}
            )
            results.append(runbook)

        return results
