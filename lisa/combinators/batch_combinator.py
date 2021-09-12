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
class BatchCombinatorSchema(schema.Combinator):
    items: List[Dict[str, Any]] = field(
        default_factory=list, metadata=field_metadata(required=True)
    )


class BatchCombinator(Combinator):
    """
    It provides a way to test a batch.

    For example,
    v1: 1, v2: 2
    v1: 2, v2: 1

    Outputs above 2 results one by one.
    """

    def __init__(self, runbook: BatchCombinatorSchema) -> None:
        super().__init__(runbook)
        batch_runbook: BatchCombinatorSchema = self.runbook

        self._items: List[Dict[str, Any]] = batch_runbook.items
        self._index = 0

    @classmethod
    def type_name(cls) -> str:
        return constants.COMBINATOR_BATCH

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BatchCombinatorSchema

    def _next(self) -> Optional[Dict[str, Any]]:
        result: Optional[Dict[str, Any]] = None
        if self._index < len(self._items):
            result = self._items[self._index]
            self._index += 1
        return result
