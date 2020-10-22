from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from lisa import schema
from lisa.util import InitializableMixin, subclasses
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
        raise NotImplementedError("must specify supported message types")

    def _received_message(self, message: MessageBase) -> None:
        raise NotImplementedError

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        initialize is optional
        """
        pass


_notifiers: List[Notifier] = []
_messages: Dict[type, List[Notifier]] = dict()


# below methods uses to operate a global notifiers,
# so that any object can send messages.
def initialize(runbooks: List[schema.Notifier]) -> None:

    factory = subclasses.Factory[Notifier](Notifier)
    log = get_logger("init", "notifier")
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
            f"on messages: [{[x.type for x in subscribed_message_types]}]"
        )

        notifier.initialize()


def notify(message: MessageBase) -> None:
    # TODO make it async for performance consideration
    notifiers = _messages.get(type(message))
    if notifiers:
        for notifier in notifiers:
            notifier._received_message(message=message)


def finalize() -> None:
    for notifier in _notifiers:
        try:
            notifier.finalize()
        except Exception as identifier:
            notifier._log.info(f"finalize failed: {identifier}")
