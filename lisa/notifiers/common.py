# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa.messages import MessageBase, TestResultMessage


def simplify_message(message: MessageBase) -> None:
    """
    This method is to reduce message length for display purpose.
    """
    if isinstance(message, TestResultMessage):
        # The description of test result is too long to display. Hide it for
        # log readability.
        description = message.information.get("description", "")
        message.information["description"] = f"<{len(description)} bytes>"
