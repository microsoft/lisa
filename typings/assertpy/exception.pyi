from typing import Any

from .assertpy import AssertionBuilder

class ExceptionMixin:
    def raises(self, ex: Any) -> AssertionBuilder: ...
    def when_called_with(
        self, *some_args: Any, **some_kwargs: Any
    ) -> AssertionBuilder: ...
