# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
from dataclasses import dataclass
from typing import Any, List, Type, cast

from dataclasses_json import dataclass_json

from lisa import notifier, schema
from lisa.testsuite import TestResultMessage
from lisa.util import constants


@dataclass_json()
@dataclass
class ConsoleSchema(schema.TypedSchema):
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

    def _received_message(self, message: notifier.MessageBase) -> None:
        self._log.log(
            getattr(logging, self._log_level),
            f"received message [{message.type}]: {message}",
        )

    def _subscribed_message_type(self) -> List[Type[notifier.MessageBase]]:
        return [TestResultMessage, notifier.TestRunMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(ConsoleSchema, self.runbook)
        self._log_level = runbook.log_level
