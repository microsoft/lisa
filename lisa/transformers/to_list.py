# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.transformer import Transformer

TO_LIST = "to_list"


@dataclass_json
@dataclass
class ToListTransformerSchema(schema.Transformer):
    # items to expand from string to list
    items: Dict[str, str] = field(default_factory=dict)
    # token to split.
    token: str = ","


class ToListTransformer(Transformer):
    """
    This transformer transfer string to a list, so the combinator can use it.
    """

    @classmethod
    def type_name(cls) -> str:
        return TO_LIST

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ToListTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        runbook: ToListTransformerSchema = self.runbook
        return [x for x in runbook.items]

    def _internal_run(self) -> Dict[str, Any]:
        runbook: ToListTransformerSchema = self.runbook
        result: Dict[str, Any] = dict()
        for name, value in runbook.items.items():
            split_values: List[str] = value.split(runbook.token)
            split_values = [x.strip() for x in split_values]
            result[name] = split_values

        return result
