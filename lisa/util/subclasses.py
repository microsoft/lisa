# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from collections import UserDict
from typing import TYPE_CHECKING, Any, Generic, Iterable, Type, TypeVar, cast

from lisa import schema
from lisa.util import BaseClassMixin, InitializableMixin, LisaException, constants
from lisa.util.logger import get_logger


class BaseClassWithRunbookMixin(BaseClassMixin):
    def __init__(self, runbook: schema.TypedSchema, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        if self.type_schema() != type(runbook):
            # reload if type is defined in subclass
            self._runbook = (
                self.type_schema().schema().load(runbook.to_dict())  # type:ignore
            )
        else:
            self._runbook = runbook

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        raise NotImplementedError()


T_BASECLASS = TypeVar("T_BASECLASS", bound=BaseClassMixin)


if TYPE_CHECKING:
    SubClassTypeDict = UserDict[str, type]
else:
    SubClassTypeDict = UserDict


class Factory(InitializableMixin, Generic[T_BASECLASS], SubClassTypeDict):
    def __init__(self, base_type: Type[T_BASECLASS]) -> None:
        super().__init__()
        self._base_type = base_type
        self._log = get_logger("subclasses", base_type.__name__)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # initialize types from subclasses.
        # each type should be unique in code, or there is warning message.
        for subclass_type in self._get_subclasses(self._base_type):
            subclass_type_name = subclass_type.type_name()
            exists_type = self.get(subclass_type_name)
            if exists_type:
                # so far, it happens on ut only.
                # When UT code import each other, it happens.
                # it's important to use first registered.
                self._log.error(
                    f"registered [{subclass_type_name}] subclass again. "
                    f"It should happen in UT only. "
                    f"new: [{subclass_type}], exist: [{exists_type}]"
                )
            else:
                self[subclass_type.type_name()] = subclass_type
        self._log.debug(
            f"registered: " f"[{', '.join([name for name in self.keys()])}]"
        )

    def create_runbook(self, raw_runbook: Any) -> T_BASECLASS:
        self.initialize()
        type_name = raw_runbook[constants.TYPE]
        sub_type = self.get(type_name)
        if sub_type is None:
            raise LisaException(
                f"cannot find subclass '{type_name}' of {self._base_type.__name__}"
            )
        instance = sub_type.schema().load(raw_runbook)  # type: ignore
        return cast(T_BASECLASS, instance)

    def create_by_type_name(
        self, type_name: str, *args: Any, **kwargs: Any
    ) -> T_BASECLASS:
        self.initialize()
        sub_type = self.get(type_name)
        if sub_type is None:
            raise LisaException(
                f"cannot find subclass '{type_name}' of {self._base_type.__name__}"
            )
        return cast(T_BASECLASS, sub_type(*args, **kwargs))

    def create_by_runbook(
        self, runbook: schema.TypedSchema, *args: Any, **kwargs: Any
    ) -> T_BASECLASS:
        self.initialize()
        sub_type = self.get(runbook.type)
        if sub_type is None:
            raise LisaException(
                f"cannot find subclass '{runbook.type}' of runbook {runbook}"
            )
        sub_type_with_runbook = cast(Type[BaseClassWithRunbookMixin], sub_type)
        sub_object = sub_type_with_runbook(runbook, *args, **kwargs)
        assert isinstance(
            sub_object, BaseClassWithRunbookMixin
        ), f"actual: {type(sub_object)}"

        return cast(T_BASECLASS, sub_object)

    def _get_subclasses(
        self, type: Type[BaseClassMixin]
    ) -> Iterable[Type[BaseClassMixin]]:
        # recursive loop subclasses of subclasses
        for subclass_type in type.__subclasses__():
            yield subclass_type
            yield from self._get_subclasses(subclass_type)
