# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, Optional

from lisa import schema
from lisa.util import InitializableMixin, LisaException, subclasses
from lisa.util.logger import get_logger
from lisa.variable import VariableEntry


class Combinator(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    """
    Expand a couple of variables with multiple value to multiple runners. So
    LISA can run once to test different combinations of variables.

    For example,
    v1: 1, 2
    v2: 1, 2

    With the grid combinations, there are 4 results:
    v1: 1, v2: 1
    v1: 2, v2: 1
    v1: 1, v2: 2
    v1: 2, v2: 2
    """

    def __init__(self, runbook: schema.Combinator) -> None:
        super().__init__(runbook=runbook)
        self._log = get_logger("combinator", self.__class__.__name__)
        # return at least once, if it's empty
        self._is_first_time = True

    def fetch(
        self, current_variables: Dict[str, VariableEntry]
    ) -> Optional[Dict[str, VariableEntry]]:
        """
        Returns a combination each time. If there is no more, it returns None.
        """
        result: Optional[Dict[str, VariableEntry]] = None

        new_variables = self._next()

        if new_variables or self._is_first_time:
            result = current_variables.copy()
            if new_variables:
                for name, new_variable in new_variables.items():
                    original_variable = result.get(name, None)
                    if original_variable:
                        copied_variable = original_variable.copy()
                        copied_variable.update(new_variable)
                        result[name] = copied_variable
                    else:
                        result[name] = new_variable

        self._is_first_time = False
        return result

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        if a combinator need long time initialization, it should be
        implemented here.
        """
        ...

    def _next(self) -> Optional[Dict[str, VariableEntry]]:
        """
        subclasses should implement this method to return a combination. Return
        None means no more.
        """
        raise NotImplementedError()

    def _validate_entry(self, entry: schema.Variable) -> None:
        """
        combinator reuse variable entry schema, but not allow the file type, and
        need the value to be a list.
        """
        if entry.file:
            raise LisaException(
                f"The value of combinator doesn't support file, "
                f"but got {entry.file}"
            )
        if not isinstance(entry.value, list):
            raise LisaException(
                f"The value of combinator must be a list, "
                f"but got {type(entry.value)}, value: {entry.value}"
            )
