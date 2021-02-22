import collections
from typing import Any

from .assertpy import AssertionBuilder

Iterable = collections.abc.Iterable
__tracebackhide__: bool

class DynamicMixin:
    def __getattr__(self, attr: Any) -> AssertionBuilder: ...
