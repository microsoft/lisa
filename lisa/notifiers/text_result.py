# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Type, cast

from dataclasses_json import dataclass_json

from lisa import messages, notifier, schema
from lisa.messages import SubTestMessage, TestResultMessage, TestResultMessageBase
from lisa.runner import print_results
from lisa.util import LisaException, constants


@dataclass_json()
@dataclass
class TextResultSchema(schema.Notifier):
    include_subtest: bool = False


class TextResult(notifier.Notifier):
    """
    Creating log notifier to dump text formatted results for easier
    view in editing mode. The original log is complete but too long to
    check only the summary.
    """

    @classmethod
    def type_name(cls) -> str:
        return "text_result"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return TextResultSchema

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, TestResultMessage):
            if message.is_completed:
                self._received_messages.append(message)
        elif isinstance(message, SubTestMessage):
            if self._include_subtest:
                self._received_messages.append(message)
        else:
            raise LisaException(f"Received unsubscribed message type: {message.type}")

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [TestResultMessage, SubTestMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._result_path = Path(
            f"{constants.RUN_LOCAL_LOG_PATH}/lisa-{constants.RUN_ID}-result.txt"
        )
        if self._result_path.exists():
            raise LisaException("File already exists")

        runbook = cast(TextResultSchema, self.runbook)

        self._include_subtest = runbook.include_subtest
        self._received_messages: List[TestResultMessageBase] = []

    def finalize(self) -> None:
        with open(self._result_path, "w") as result_file:
            print_results(self._received_messages, result_file.write, add_ending=True)
