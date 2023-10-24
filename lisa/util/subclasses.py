# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from collections import UserDict
from typing import TYPE_CHECKING, Any, Generic, Iterable, Type, TypeVar, cast

from lisa import schema
from lisa.util import BaseClassMixin, InitializableMixin, LisaException, constants
from lisa.util.logger import get_logger


class BaseClassWithRunbookMixin(BaseClassMixin):
    def __init__(self, runbook: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.runbook = runbook

    @classmethod
    def create_with_runbook(
        cls, runbook: schema.TypedSchema, **kwargs: Any
    ) -> "BaseClassWithRunbookMixin":
        if cls.type_schema() != type(runbook):
            # reload if type is defined in subclass
            runbook = schema.load_by_type(cls.type_schema(), runbook)
        return cls(runbook=runbook, **kwargs)

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
                raise LisaException(
                    f"registered [{subclass_type_name}] subclass again. "
                    f"It should happen in UT only. "
                    f"new: [{subclass_type}], exist: [{exists_type}]"
                )
            else:
                self[subclass_type.type_name()] = subclass_type
        self._log.debug(
            f"registered: " f"[{', '.join([name for name in self.keys()])}]"
        )

    def load_typed_runbook(self, raw_runbook: Any) -> T_BASECLASS:
        type_name = raw_runbook[constants.TYPE]
        sub_type = self._get_sub_type(type_name)
        instance: Any = schema.load_by_type(sub_type, raw_runbook)
        if hasattr(instance, "extended_schemas"):
            if instance.extended_schemas:
                raise LisaException(
                    f"found unknown fields: {instance.extended_schemas}"
                )
        return cast(T_BASECLASS, instance)

    def create_by_type_name(self, type_name: str, **kwargs: Any) -> T_BASECLASS:
        sub_type = self._get_sub_type(type_name)

        return cast(T_BASECLASS, sub_type(**kwargs))

    def create_by_runbook(
        self, runbook: schema.TypedSchema, **kwargs: Any
    ) -> T_BASECLASS:
        sub_type = self._get_sub_type(runbook.type)
        sub_type_with_runbook = cast(Type[BaseClassWithRunbookMixin], sub_type)
        sub_object = sub_type_with_runbook.create_with_runbook(
            runbook=runbook, **kwargs
        )
        assert isinstance(
            sub_object, BaseClassWithRunbookMixin
        ), f"actual: {type(sub_object)}"

        return cast(T_BASECLASS, sub_object)

    def _get_subclasses(
        self, cls: Type[BaseClassMixin]
    ) -> Iterable[Type[BaseClassMixin]]:
        # recursive loop subclasses of subclasses
        for subclass_type in cls.__subclasses__():
            yield subclass_type
            yield from self._get_subclasses(subclass_type)

    def _get_sub_type(self, type_name: str) -> type:
        self.initialize()
        sub_type = self.get(type_name)
        if sub_type is None:
            raise LisaException(
                f"cannot find subclass '{type_name}' of {self._base_type.__name__}. "
                f"Supported types include: {list(self.keys())}. "
                f"Are you missing an import in 'mixin_modules.py' or an extension?"
            )
        return sub_type
