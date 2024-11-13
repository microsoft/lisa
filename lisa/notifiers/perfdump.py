# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, List, Type, cast

from dataclasses_json import dataclass_json

from lisa import constants, messages, notifier, schema


@dataclass_json()
@dataclass
class PerfDumpSchema(schema.Notifier):
    path: str = "perf_results.json"


class PerfDump(notifier.Notifier):
    """
    The Json notifier is used to output the perf test results in JSON format.
    """

    _first_message_written: bool = False

    @classmethod
    def type_name(cls) -> str:
        return "perfdump"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PerfDumpSchema

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, messages.PerfMessage):
            message_dict = {}
            for key, value in message.__dict__.items():
                if isinstance(value, Enum):
                    value = value.value
                elif isinstance(value, datetime) or isinstance(value, Decimal):
                    value = str(value)
                message_dict[key] = value
            if self._first_message_written:
                self._report_file.write(",\n")
            else:
                self._first_message_written = True
            json.dump(message_dict, self._report_file, indent=4, ensure_ascii=False)

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [messages.PerfMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(PerfDumpSchema, self.runbook)
        self._report_path = constants.RUN_LOCAL_LOG_PATH / runbook.path
        self._report_file = open(self._report_path, "a", encoding="utf-8")
        if os.path.getsize(self._report_path) == 0:
            self._report_file.write("[")

    def finalize(self) -> None:
        try:
            self._report_file.write("]")
        finally:
            self._report_file.close()
