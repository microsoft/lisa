# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Dict, List
from unittest.case import TestCase

from lisa import constants
from lisa.combinators.batch_combinator import BatchCombinator, BatchCombinatorSchema
from lisa.variable import VariableEntry


class BatchCombinatorTestCase(TestCase):
    def test_batch_combinator_two(self) -> None:
        expected_collection: List[Dict[str, str]] = [
            {"name1": "1value1", "name2": "2value1", "name3": "3value1"},
            {"name1": "1value2", "name2": "2value1", "name3": "3value1"},
        ]
        runbook = BatchCombinatorSchema(
            type=constants.COMBINATOR_BATCH,
            items=[
                {"name1": "1value1", "name2": "2value1"},
                {"name1": "1value2", "name2": "2value1"},
            ],
        )

        current: Dict[str, VariableEntry] = {}
        current["name2"] = VariableEntry("name2", "2value0")
        current["name3"] = VariableEntry("name3", "3value1")
        combinator = BatchCombinator(runbook=runbook)
        actual_collection: List[Dict[str, VariableEntry]] = []
        while True:
            item = combinator.fetch(current)
            if item:
                actual_collection.append(item)
            else:
                break

        # self.assertEqual(len(expected_collection), len(actual_collection))
        for index, actual_item in enumerate(actual_collection):
            expected_item = expected_collection[index]
            for name, expected_value in expected_item.items():
                actual_entry = actual_item[name]
                self.assertEqual(
                    expected_value,
                    actual_entry.data,
                    f"name: {name}, actual: {actual_entry}",
                )

    def test_batch_combinator_empty(self) -> None:
        expected_collection: List[Dict[str, str]] = []
        runbook = BatchCombinatorSchema(
            type=constants.COMBINATOR_BATCH,
            items=[],
        )

        current: Dict[str, VariableEntry] = {}
        current["name3"] = VariableEntry("name3", "3value1")
        combinator = BatchCombinator(runbook=runbook)
        actual_collection: List[Dict[str, VariableEntry]] = []
        while True:
            item = combinator.fetch(current)
            if item:
                actual_collection.append(item)
            else:
                break

        self.assertEqual(len(expected_collection), len(actual_collection))
        for index, actual_item in enumerate(actual_collection):
            expected_item = expected_collection[index]
            for name, expected_value in expected_item.items():
                actual_entry = actual_item[name]
                self.assertEqual(
                    expected_value,
                    actual_entry.data,
                    f"name: {name}, actual: {actual_entry}",
                )
