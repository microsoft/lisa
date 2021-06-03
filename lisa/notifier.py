# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from lisa import schema
from lisa.util import InitializableMixin, constants, subclasses
from lisa.util.logger import get_logger


@dataclass
class MessageBase:
    type: str = ""
    elapsed: float = 0


TestRunStatus = Enum(
    "TestRunStatus",
    [
        "INITIALIZING",
        "RUNNING",
        "SUCCESS",
        "FAILED",
    ],
)


@dataclass
class TestRunMessage(MessageBase):
    type: str = "TestRun"
    status: TestRunStatus = TestRunStatus.INITIALIZING
    test_project: str = ""
    test_pass: str = ""
    tags: Optional[List[str]] = None
    run_name: str = ""
    message: str = ""


class Notifier(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(self, runbook: schema.TypedSchema) -> None:
        super().__init__(runbook=runbook)
        self._log = get_logger("notifier", self.__class__.__name__)

    def finalize(self) -> None:
        """
        All test done. notifier should release resource,
        or do finalize work, like save to a file.

        Even failed, this method will be called.
        """
        pass

    def _subscribed_message_type(self) -> List[Type[MessageBase]]:
        """
        Specify which message types want to be subscribed.
        Other types won't be passed in.
        """
        raise NotImplementedError("must specify supported message types")

    def _received_message(self, message: MessageBase) -> None:
        """
        Called by notifier, when a subscribed message happens.
        """
        raise NotImplementedError

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        initialize is optional
        """
        pass


_notifiers: List[Notifier] = []
_messages: Dict[type, List[Notifier]] = dict()
# prevent concurrent message conflict.
_message_queue: List[MessageBase] = []
_message_queue_lock = threading.Lock()
_notifying_lock = threading.Lock()


# below methods uses to operate a global notifiers,
# so that any object can send messages.
def initialize(runbooks: List[schema.Notifier]) -> None:

    factory = subclasses.Factory[Notifier](Notifier)
    log = get_logger("init", "notifier")
    if not any(x for x in runbooks if x.type == constants.NOTIFIER_CONSOLE):
        # add console notifier by default to provide troubleshooting information
        runbooks.append(schema.Notifier(type=constants.NOTIFIER_CONSOLE))
    for runbook in runbooks:
        notifier = factory.create_by_runbook(runbook=runbook)
        _notifiers.append(notifier)

        subscribed_message_types: List[
            Type[MessageBase]
        ] = notifier._subscribed_message_type()

        for message_type in subscribed_message_types:
            registered_notifiers = _messages.get(message_type, [])
            registered_notifiers.append(notifier)
            _messages[message_type] = registered_notifiers
        log.debug(
            f"registered [{notifier.type_name()}] "
            f"on messages: {[x.type for x in subscribed_message_types]}"
        )

        notifier.initialize()


def notify(message: MessageBase) -> None:
    # TODO make it async for performance consideration

    # to make sure message get order as possible, use a queue to hold messages.
    with _message_queue_lock:
        _message_queue.append(message)
    while len(_message_queue) > 0:
        # send message one by one
        with _notifying_lock:
            with _message_queue_lock:
                current_message: Optional[MessageBase] = None
                if len(_message_queue) > 0:
                    current_message = _message_queue.pop()
            if current_message:
                notifiers = _messages.get(type(current_message))
                if notifiers:
                    for notifier in notifiers:
                        notifier._received_message(message=current_message)


def finalize() -> None:
    for notifier in _notifiers:
        try:
            notifier.finalize()
        except Exception as identifier:
            notifier._log.exception(identifier)
