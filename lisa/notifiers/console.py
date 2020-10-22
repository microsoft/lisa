import logging
from dataclasses import dataclass
from typing import List, Type, cast

from dataclasses_json import LetterCase, dataclass_json  # type: ignore

from lisa import notifier, schema
from lisa.testsuite import TestResultMessage


@dataclass_json(letter_case=LetterCase.CAMEL)
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
        return "console"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ConsoleSchema

    def _received_message(self, message: notifier.MessageBase) -> None:
        runbook = cast(ConsoleSchema, self._runbook)
        self._log.log(
            getattr(logging, runbook.log_level),
            f"received message [{message.type}]: {message}",
        )

    def _subscribed_message_type(self) -> List[Type[notifier.MessageBase]]:
        return [TestResultMessage, notifier.TestRunMessage]
