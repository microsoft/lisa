import collections
from typing import Any

from .assertpy import AssertionBuilder

str_types: Any
Iterable = collections.abc.Iterable
__tracebackhide__: bool

class ExtractingMixin:
    def extracting(self, *names: Any, **kwargs: Any) -> AssertionBuilder: ...
