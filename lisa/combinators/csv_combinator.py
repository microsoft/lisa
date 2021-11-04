# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import csv
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, Union

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.combinator import Combinator


@dataclass_json()
@dataclass
class Entry:
    column: str
    variable: str
    default: Union[str, bool, int] = ""


@dataclass_json()
@dataclass
class CsvCombinatorSchema(schema.Combinator):
    file_name: str = ""
    # map csv column to variable name
    column_mapping: List[Entry] = field(default_factory=list)


class CsvCombinator(Combinator):
    """
    It provides a way to read from csv to fill the variables
    """

    def __init__(self, runbook: CsvCombinatorSchema) -> None:
        super().__init__(runbook)
        self._index = 0

    @classmethod
    def type_name(cls) -> str:
        return "csv"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return CsvCombinatorSchema

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook: CsvCombinatorSchema = self.runbook
        self._items: List[Dict[str, Any]] = []
        with open(runbook.file_name, "r", encoding="utf-8-sig") as f:
            results = csv.DictReader(f)
            for row in results:
                new_collection: Dict[str, Any] = {}
                for entry in runbook.column_mapping:
                    value = row.get(entry.column, entry.default)
                    if entry.default and not value:
                        value = entry.default
                    new_collection[entry.variable] = value
                self._items.append(new_collection)

    def _next(self) -> Optional[Dict[str, Any]]:
        result: Optional[Dict[str, Any]] = None
        if self._index < len(self._items):
            result = self._items[self._index]
            self._index += 1
        return result
