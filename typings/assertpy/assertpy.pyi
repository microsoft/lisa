import logging
from typing import Any, Optional

from .base import BaseMixin as BaseMixin
from .collection import CollectionMixin as CollectionMixin
from .contains import ContainsMixin as ContainsMixin
from .date import DateMixin as DateMixin
from .dict import DictMixin as DictMixin
from .dynamic import DynamicMixin as DynamicMixin
from .exception import ExceptionMixin as ExceptionMixin
from .extracting import ExtractingMixin as ExtractingMixin
from .file import FileMixin as FileMixin
from .helpers import HelpersMixin as HelpersMixin
from .numeric import NumericMixin as NumericMixin
from .snapshot import SnapshotMixin as SnapshotMixin
from .string import StringMixin as StringMixin

def soft_assertions() -> None: ...
def assert_that(val: Any, description: str = ...) -> AssertionBuilder: ...
def assert_warn(
    val: Any, description: str = ..., logger: Optional[Any] = ...
) -> AssertionBuilder: ...
def fail(msg: str = ...) -> None: ...
def soft_fail(msg: str = ...) -> None: ...
def add_extension(func: Any) -> None: ...
def remove_extension(func: Any) -> None: ...

class WarningLoggingAdapter(logging.LoggerAdapter):  # type: ignore
    def process(self, msg: Any, kwargs: Any) -> Any: ...

class AssertionBuilder(
    StringMixin,
    SnapshotMixin,
    NumericMixin,
    HelpersMixin,
    FileMixin,
    ExtractingMixin,
    ExceptionMixin,
    DynamicMixin,
    DictMixin,
    DateMixin,
    ContainsMixin,
    CollectionMixin,
    BaseMixin,
):
    val: Any = ...
    description: Any = ...
    kind: Any = ...
    expected: Any = ...
    logger: Any = ...
    def __init__(
        self,
        val: Any,
        description: str = ...,
        kind: Optional[Any] = ...,
        expected: Optional[Any] = ...,
        logger: Optional[Any] = ...,
    ) -> None: ...
    def builder(
        self,
        val: Any,
        description: str = ...,
        kind: Optional[Any] = ...,
        expected: Optional[Any] = ...,
        logger: Optional[Any] = ...,
    ) -> AssertionBuilder: ...
    def error(self, msg: Any) -> AssertionBuilder: ...
