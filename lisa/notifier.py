# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import threading
from datetime import datetime, timezone
from functools import partial
from typing import Any, Dict, List, Optional, Type

from lisa import schema
from lisa.messages import MessageBase
from lisa.util import InitializableMixin, constants, subclasses
from lisa.util.logger import get_logger
from lisa.util.parallel import run_in_parallel

_get_init_logger = partial(get_logger, "init", "notifier")


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
_messages: Dict[type, List[Notifier]] = {}
# prevent concurrent message conflict.
_message_queue: List[MessageBase] = []
_message_queue_lock = threading.Lock()
_notifying_lock = threading.Lock()
_system_notifiers = [constants.NOTIFIER_CONSOLE, constants.NOTIFIER_FILE]


def initialize(runbooks: List[schema.Notifier]) -> None:
    factory = subclasses.Factory[Notifier](Notifier)
    log = _get_init_logger()

    # add system notifiers to provide troubleshooting information
    names = (x.type.lower() for x in runbooks)
    for system_notifier in _system_notifiers:
        if system_notifier not in names:
            runbooks.append(schema.Notifier(type=system_notifier))

    for runbook in runbooks:
        if not runbook.enabled:
            log.debug(f"skipped notifier [{runbook.type}], because it's not enabled.")
            continue

        notifier = factory.create_by_runbook(runbook=runbook)
        register_notifier(notifier)


def register_notifier(notifier: Notifier) -> None:
    """
    register internal notifiers
    """
    notifier.initialize()

    _notifiers.append(notifier)
    subscribed_message_types: List[
        Type[MessageBase]
    ] = notifier._subscribed_message_type()

    for message_type in subscribed_message_types:
        registered_notifiers = _messages.get(message_type, [])
        registered_notifiers.append(notifier)
        _messages[message_type] = registered_notifiers

    log = _get_init_logger()
    log.debug(
        f"registered [{notifier.type_name()}] "
        f"on messages: {[x.type for x in subscribed_message_types]}"
    )


def notify(message: MessageBase) -> None:
    if message.time is None:
        # if time is not set, set it to now
        message.time = datetime.now(timezone.utc)

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
                message_types = type(current_message).__mro__
                for message_type in message_types:
                    notifiers = _messages.get(message_type, [])
                    if notifiers:
                        run_in_parallel(
                            [
                                partial(
                                    x._received_message,
                                    message=copy.deepcopy(current_message),
                                )
                                for x in notifiers
                            ]
                        )
                    if message_type == MessageBase:
                        # skip the object type
                        break


def finalize() -> None:
    for notifier in _notifiers:
        try:
            notifier.finalize()
        except Exception as e:
            notifier._log.exception(e)
