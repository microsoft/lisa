from typing import Any, Optional

from .assertpy import AssertionBuilder

class SnapshotMixin:
    def snapshot(
        self, id: Optional[Any] = ..., path: str = ...
    ) -> AssertionBuilder: ...
