# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.combinator import Combinator
from lisa.util import constants, field_metadata


@dataclass_json()
@dataclass
class GridCombinatorSchema(schema.Combinator):
    items: List[schema.Variable] = field(
        default_factory=list, metadata=field_metadata(required=True)
    )


class GridCombinator(Combinator):
    """
    It provides a grid search result for each combination.

    For example,
    v1: 1, 2
    v2: 1, 2

    Output 4 results:
    v1: 1, v2: 1
    v1: 2, v2: 1
    v1: 1, v2: 2
    v1: 2, v2: 2
    """

    def __init__(self, runbook: GridCombinatorSchema) -> None:
        super().__init__(runbook)
        grid_runbook: GridCombinatorSchema = self.runbook
        grid_items = grid_runbook.items

        self._items: List[schema.Variable] = grid_items
        self._indexes = [0] * len(grid_items)
        self._sizes = [0] * len(grid_items)
        # set first to -1 for first round
        if self._indexes:
            self._indexes[0] = -1
        # validate each item must be a list
        for index, item in enumerate(grid_items):
            self._validate_entry(item)
            assert isinstance(item.value, list)
            self._sizes[index] = len(item.value)

    @classmethod
    def type_name(cls) -> str:
        return constants.COMBINATOR_GRID

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return GridCombinatorSchema

    def _next(self) -> Optional[Dict[str, Any]]:
        result: Optional[Dict[str, Any]] = None
        is_overflow: bool = False
        carry = 1
        for item_index in range(len(self._indexes)):
            current_index = self._indexes[item_index]
            total = carry + current_index
            carry = int(total / self._sizes[item_index])
            self._indexes[item_index] = total % self._sizes[item_index]

            if item_index == len(self._sizes) - 1 and carry:
                is_overflow = True
            if not carry:
                break

        if not is_overflow and self._items:
            result = {}
            for index, item in enumerate(self._items):
                assert isinstance(item.value, list)
                result[item.name] = item.value[self._indexes[index]]
        return result
