from typing import Any

from .assertpy import AssertionBuilder

class DynamicMixin:
    def __getattr__(self, attr: Any) -> AssertionBuilder: ...
