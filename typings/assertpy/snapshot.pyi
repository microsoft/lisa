from typing import Any, Optional

from .assertpy import AssertionBuilder

__tracebackhide__: bool

class SnapshotMixin:
    def snapshot(
        self, id: Optional[Any] = ..., path: str = ...
    ) -> AssertionBuilder: ...
