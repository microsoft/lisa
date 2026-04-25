# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import os
from datetime import datetime, timezone
from functools import partial
from typing import Any, Dict, List, Type, cast

from lisa import schema
from lisa.messages import MessageBase
from lisa.util import InitializableMixin, constants, subclasses
from lisa.util.logger import get_logger
from lisa.util.parallel import Task, TaskManager

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

    def _modify_message(self, message: MessageBase) -> None:
        """
        Called before _received_message, can be used to modify messages for all
        notifiers.
        """
        pass


_notifiers: List[Notifier] = []
_messages: Dict[type, List[Notifier]] = {}
_system_notifiers = [constants.NOTIFIER_CONSOLE, constants.NOTIFIER_FILE]
# Use multiple workers to avoid serializing all notifications during
# concurrent test execution. The original max_workers=1 created a
# throughput bottleneck when log volume was high.
_notification_workers = min(os.cpu_count() or 4, 8)
_message_manager: TaskManager[None] = TaskManager(max_workers=_notification_workers)


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

    # Sort notifiers by priority (smaller priority first)
    _notifiers.sort(key=lambda x: cast(schema.Notifier, x.runbook).priority)

    # Sort notifiers in each message type list by priority
    for message_type in _messages:
        _messages[message_type].sort(
            key=lambda x: cast(schema.Notifier, x.runbook).priority
        )


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

    _message_manager.submit_task(
        Task(
            task_id=0,
            task=partial(_notify, message),
            parent_logger=_get_init_logger(),
        )
    )


def _notify(message: MessageBase) -> None:
    message_types = type(message).__mro__
    for message_type in message_types:
        notifiers = _messages.get(message_type, [])
        for notifier in notifiers:
            notifier._modify_message(message)

        # Dispatch to notifiers directly instead of spawning a new
        # ThreadPoolExecutor per message via run_in_parallel. With multiple
        # notification workers processing messages concurrently, the overhead
        # of creating/destroying a thread pool per message far exceeds the
        # benefit of per-message notifier parallelism.
        for notifier in notifiers:
            notifier._received_message(message=copy.deepcopy(message))

        if message_type == MessageBase:
            # skip base class type: object
            break


def flush_notifications() -> None:
    assert _message_manager, "The message manager is not initialized"
    _message_manager.wait_for_all_workers()


def finalize() -> None:
    flush_notifications()

    for notifier in _notifiers:
        try:
            notifier.finalize()
        except Exception as e:
            notifier._log.exception(e)
