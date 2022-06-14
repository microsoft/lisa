# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any, List, Type

from lisa import messages, notifier, schema
from lisa.messages import TestResultMessage
from lisa.runner import print_results
from lisa.util import LisaException, constants


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
        return schema.Notifier

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, TestResultMessage):
            if message.is_completed:
                self.received_messages.append(message)
        else:
            raise LisaException("Received unsubscribed message type")

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [TestResultMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.result_path = Path(
            f"{constants.RUN_LOCAL_LOG_PATH}/lisa-{constants.RUN_ID}-result.txt"
        )
        if self.result_path.exists():
            raise LisaException("File already exists")

        self.received_messages: List[TestResultMessage] = []

    def finalize(self) -> None:
        with open(self.result_path, "w") as result_file:
            print_results(self.received_messages, result_file.write)
