# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
from dataclasses import dataclass
from typing import Any, List, Type, cast

from dataclasses_json import dataclass_json

from lisa import messages, notifier, schema
from lisa.util import constants

from .common import simplify_message


@dataclass_json()
@dataclass
class ConsoleSchema(schema.Notifier):
    log_level: str = logging.getLevelName(logging.DEBUG)


class Console(notifier.Notifier):
    """
    It's a sample notifier, output subscribed message to console.
    It can be used to troubleshooting what kind of message received.
    """

    @classmethod
    def type_name(cls) -> str:
        return constants.NOTIFIER_CONSOLE

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ConsoleSchema

    def _received_message(self, message: messages.MessageBase) -> None:
        simplify_message(message)
        self._log.log(
            getattr(logging, self._log_level),
            f"received message [{message.type}]: {message}",
        )

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [messages.MessageBase]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(ConsoleSchema, self.runbook)
        self._log_level = runbook.log_level
