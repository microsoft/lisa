from typing import Any

from .assertpy import AssertionBuilder

class ExtractingMixin:
    def extracting(self, *names: Any, **kwargs: Any) -> AssertionBuilder: ...
