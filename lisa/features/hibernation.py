# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass
from functools import partial
from typing import Any, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema, search_space
from lisa.feature import Feature

FEATURE_NAME_HIBERNATION = "Hibernation"


@dataclass_json()
@dataclass()
class HibernationSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_HIBERNATION
    is_enabled: bool = False

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.is_enabled}"

    def _generate_min_capability(self, capability: Any) -> Any:
        return self

    def check(self, capability: Any) -> search_space.ResultReason:
        result = super().check(capability)

        result.merge(
            search_space.check_countspace(self.is_enabled, capability.is_enabled),
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
