# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from functools import partial
from typing import Any, List, Type, Union, cast

from dataclasses_json import dataclass_json

from lisa import schema, search_space
from lisa.feature import Feature
from lisa.util import field_metadata

FEATURE_NAME_HIBERNATION = "Hibernation"

false_priority: List[bool] = [False, True]


@dataclass_json()
@dataclass()
class HibernationSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_HIBERNATION
    is_enabled: Union[search_space.SetSpace[bool], bool] = field(
        default_factory=partial(
            search_space.SetSpace[bool], is_allow_set=True, items=[True, False]
        ),
        metadata=field_metadata(
            decoder=partial(search_space.decode_set_space_by_type, base_type=bool)
        ),
    )

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.is_enabled}"

    def _call_requirement_method(
        self, method: search_space.RequirementMethod, capability: Any
    ) -> Any:
        assert isinstance(
            capability, HibernationSettings
        ), f"actual: {type(capability)}"

        value = HibernationSettings()
        value.is_enabled = getattr(
            search_space, f"{method.value}_setspace_by_priority"
        )(
            self.is_enabled,
            capability.is_enabled,
            false_priority,
        )
        return value

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, HibernationSettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)
        result.merge(
            search_space.check_setspace(self.is_enabled, capability.is_enabled),
            "is_enabled",
        )
        return result


class Hibernation(Feature):
    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        settings = cast(HibernationSettings, kwargs.get("settings"))
        if settings.is_enabled:
            cls._enable_hibernation(*args, **kwargs)

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_HIBERNATION

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return HibernationSettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    @classmethod
    def _enable_hibernation(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    def enabled(self) -> bool:
        return True


HibernationEnabled = partial(HibernationSettings, is_enabled=True)
