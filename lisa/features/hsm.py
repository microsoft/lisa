# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from functools import partial
from typing import Any, Type, Union, cast

from dataclasses_json import dataclass_json

from lisa import schema, search_space
from lisa.feature import Feature
from lisa.util import field_metadata

FEATURE_NAME_HSM = "Hsm"


@dataclass_json()
@dataclass()
class HsmSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_HSM
    is_enabled: Union[search_space.SetSpace[bool], bool] = field(
        default=True,
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
        assert isinstance(capability, HsmSettings), f"actual: {type(capability)}"
        value = HsmSettings()
        value.is_enabled = getattr(
            search_space, f"{method.value}_setspace_by_priority"
        )(self.is_enabled, capability.is_enabled, [False, True])
        return value

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(capability, HsmSettings), f"actual: {type(capability)}"
        result = super().check(capability)
        result.merge(
            search_space.check_setspace(self.is_enabled, capability.is_enabled),
            "is_enabled",
        )
        return result


class Hsm(Feature):
    """Identifies VMs with an integrated hardware security module."""

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_HSM

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return HsmSettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        settings = cast(HsmSettings, self._settings)
        assert isinstance(settings.is_enabled, bool)
        return settings.is_enabled
