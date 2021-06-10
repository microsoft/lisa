# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Dict, List
from unittest.case import TestCase

from lisa import schema
from lisa.combinators.grid_combinator import GridCombinator, GridCombinatorSchema
from lisa.util import constants
from lisa.variable import VariableEntry


class GridCombinatorTestCase(TestCase):
    def test_grid_combinator_full_matrix(self) -> None:
        expected_collection: List[Dict[str, str]] = [
            {"name1": "1value1", "name2": "2value1", "name3": "3value1"},
            {"name1": "1value2", "name2": "2value1", "name3": "3value1"},
            {"name1": "1value1", "name2": "2value2", "name3": "3value1"},
            {"name1": "1value2", "name2": "2value2", "name3": "3value1"},
            {"name1": "1value1", "name2": "2value3", "name3": "3value1"},
            {"name1": "1value2", "name2": "2value3", "name3": "3value1"},
        ]
        runbook = GridCombinatorSchema(
            type=constants.COMBINATOR_GRID,
            items=[
                schema.Variable(name="name1", value_raw=["1value1", "1value2"]),
                schema.Variable(
                    name="name2", value_raw=["2value1", "2value2", "2value3"]
                ),
            ],
        )

        current: Dict[str, VariableEntry] = dict()
        current["name2"] = VariableEntry("name2", "2value0")
        current["name3"] = VariableEntry("name3", "3value1")
        combinator = GridCombinator(runbook=runbook)
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

    def test_grid_combinator_empty(self) -> None:
        expected_collection: List[Dict[str, str]] = [
            {"name3": "3value1"},
        ]
        runbook = GridCombinatorSchema(
            type=constants.COMBINATOR_GRID,
            items=[],
        )

        current: Dict[str, VariableEntry] = dict()
        current["name3"] = VariableEntry("name3", "3value1")
        combinator = GridCombinator(runbook=runbook)
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

    def test_grid_combinator_one_dimension(self) -> None:
        expected_collection: List[Dict[str, str]] = [
            {"name2": "2value1", "name3": "3value1"},
            {"name2": "2value2", "name3": "3value1"},
            {"name2": "2value3", "name3": "3value1"},
        ]
        runbook = GridCombinatorSchema(
            type=constants.COMBINATOR_GRID,
            items=[
                schema.Variable(
                    name="name2", value_raw=["2value1", "2value2", "2value3"]
                ),
            ],
        )

        current: Dict[str, VariableEntry] = dict()
        current["name2"] = VariableEntry("name2", "2value0")
        current["name3"] = VariableEntry("name3", "3value1")
        combinator = GridCombinator(runbook=runbook)
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
