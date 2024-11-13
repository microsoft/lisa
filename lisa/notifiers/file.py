# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Type, cast

from dataclasses_json import dataclass_json

from lisa import messages, notifier, schema
from lisa.util import constants

from .common import simplify_message


@dataclass_json()
@dataclass
class ConsoleSchema(schema.Notifier):
    file_name: str = "messages.log"


class Console(notifier.Notifier):
    """
    It's a sample notifier, output subscribed message to file. It can be used to
    troubleshooting what kind of message received together.
    """

    @classmethod
    def type_name(cls) -> str:
        return constants.NOTIFIER_FILE

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ConsoleSchema

    def finalize(self) -> None:
        return super().finalize()

    def _received_message(self, message: messages.MessageBase) -> None:
        simplify_message(message)
        # write every time to refresh the content immediately.
        with open(self._file_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S.%ff}: {message}\n")

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [messages.MessageBase]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(ConsoleSchema, self.runbook)
        self._file_path = constants.RUN_LOCAL_LOG_PATH / runbook.file_name
