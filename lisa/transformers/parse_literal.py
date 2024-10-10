# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from ast import literal_eval
from dataclasses import dataclass, field
from typing import Any, Dict, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.transformer import Transformer

PARSE_LITERAL = "parse_literal"


@dataclass_json
@dataclass
class ParseLiteralTransformerSchema(schema.Transformer):
    # items to expand from string to list
    items: Dict[str, str] = field(default_factory=dict)


class ParseLiteralTransformer(Transformer):
    """
    This transformer transfer string to a literal
    (list, set, dictionary, int, float, etc.)
    """

    @classmethod
    def type_name(cls) -> str:
        return PARSE_LITERAL

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ParseLiteralTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        runbook: ParseLiteralTransformerSchema = self.runbook
        return [x for x in runbook.items]

    def _internal_run(self) -> Dict[str, Any]:
        runbook: ParseLiteralTransformerSchema = self.runbook
        result: Dict[str, Any] = dict()
        for name, value in runbook.items.items():
            result[name] = literal_eval(value)

        return result
