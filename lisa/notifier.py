# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import threading
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from functools import partial
from typing import Any, Dict, List, Optional, Type

from lisa import schema
from lisa.util import InitializableMixin, constants, subclasses
from lisa.util.logger import get_logger


@dataclass
class MessageBase:
    type: str = "Base"
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


@dataclass
class PerfMessage(MessageBase):
    type: str = "Performance"


DiskSetupType = Enum(
    "DiskSetupType",
    [
        "raw",
        "raid0",
    ],
)


DiskType = Enum(
    "DiskType",
    [
        "nvme",
        "premiumssd",
    ],
)


@dataclass
class DiskPerformanceMessage(PerfMessage):
    tool: str = constants.DISK_PERFORMANCE_TOOL
    test_case_name: str = ""
    platform: str = ""
    location: str = ""
    host_version: str = ""
    guest_os_type: str = "Linux"
    distro_version: str = ""
    vmsize: str = ""
    kernel_version: str = ""
    lis_version: str = ""
    disk_setup_type: DiskSetupType = DiskSetupType.raw
    block_size: int = 0
    disk_type: DiskType = DiskType.nvme
    core_count: int = 0
    disk_count: int = 0
    qdepth: int = 0
    iodepth: int = 0
    numjob: int = 0
    test_date: datetime = datetime.utcnow()
    read_iops: Decimal = Decimal(0)
    read_lat_usec: Decimal = Decimal(0)
    randread_iops: Decimal = Decimal(0)
    randread_lat_usec: Decimal = Decimal(0)
    write_iops: Decimal = Decimal(0)
    write_lat_usec: Decimal = Decimal(0)
    randwrite_iops: Decimal = Decimal(0)
    randwrite_lat_usec: Decimal = Decimal(0)


@dataclass
class NetworkLatencyPerformanceMessage(PerfMessage):
    test_case_name: str = ""
    platform: str = ""
    location: str = ""
    host_version: str = ""
    guest_os_type: str = "Linux"
    distro_version: str = ""
    vmsize: str = ""
    kernel_version: str = ""
    lis_version: str = ""
    ip_version: str = "IPv4"
    protocol_type: str = "TCP"
    data_path: str = ""
    test_date: datetime = datetime.utcnow()
    max_latency_us: Decimal = Decimal(0)
    average_latency_us: Decimal = Decimal(0)
    min_latency_us: Decimal = Decimal(0)
    latency95_percentile_us: Decimal = Decimal(0)
    latency99_percentile_us: Decimal = Decimal(0)
    interval_us: int = 0
    frequency: int = 0


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


# below methods uses to operate a global notifiers,
# so that any object can send messages.
def initialize(runbooks: List[schema.Notifier]) -> None:

    factory = subclasses.Factory[Notifier](Notifier)
    log = _get_init_logger()

    if not any(x for x in runbooks if x.type == constants.NOTIFIER_CONSOLE):
        # add console notifier by default to provide troubleshooting information
        runbooks.append(schema.Notifier(type=constants.NOTIFIER_CONSOLE))

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
                message_types = type(current_message).__mro__
                for message_type in message_types:
                    notifiers = _messages.get(message_type, [])
                    for notifier in notifiers:
                        notifier._received_message(message=current_message)
                    if message_type == MessageBase:
                        # skip the object type
                        break


def finalize() -> None:
    for notifier in _notifiers:
        try:
            notifier.finalize()
        except Exception as identifier:
            notifier._log.exception(identifier)
