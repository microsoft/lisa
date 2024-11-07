# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import Any, Type, Union

from dataclasses_json import dataclass_json

from lisa import schema, search_space
from lisa.feature import Feature
from lisa.util import constants, field_metadata

FEATURE_NAME_AVAILABILITY = "Availability"


class AvailabilityType(str, Enum):
    Default = constants.AVAILABILITY_DEFAULT
    NoRedundancy = constants.AVAILABILITY_NONE
    AvailabilitySet = constants.AVAILABILITY_SET
    AvailabilityZone = constants.AVAILABILITY_ZONE


@dataclass_json()
@dataclass()
class AvailabilitySettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_AVAILABILITY
    availability_type: Union[
        search_space.SetSpace[AvailabilityType], AvailabilityType
    ] = field(  # type:ignore
        default_factory=partial(
            search_space.SetSpace,
            is_allow_set=True,
            items=[
                AvailabilityType.NoRedundancy,
                AvailabilityType.AvailabilitySet,
                AvailabilityType.AvailabilityZone,
            ],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_nullable_set_space,
                base_type=AvailabilityType,
                default_values=[
                    AvailabilityType.NoRedundancy,
                    AvailabilityType.AvailabilitySet,
                    AvailabilityType.AvailabilityZone,
                ],
                is_allow_set=True,
            )
        ),
    )
    availability_zones: search_space.SetSpace[int] = field(
        default_factory=partial(
            search_space.SetSpace[int],
            is_allow_set=True,
            items=[],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_nullable_set_space,
                base_type=int,
                default_values=[],
                is_allow_set=True,
            )
        ),
    )

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.availability_type}/{self.availability_zones}"

    def _call_requirement_method(
        self, method: search_space.RequirementMethod, capability: Any
    ) -> Any:
        assert isinstance(
            capability, AvailabilitySettings
        ), f"actual: {type(capability)}"
        value = type(self)()
        if isinstance(self.availability_type, AvailabilityType):
            self.availability_type = search_space.SetSpace(
                is_allow_set=True, items=[self.availability_type]
            )
        value.availability_type = self.availability_type.intersect(
            capability.availability_type
        )
        if self.availability_zones:
            value.availability_zones = self.availability_zones.intersect(
                capability.availability_zones
            )
        else:
            value.availability_zones = capability.availability_zones
        return value

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, AvailabilitySettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)
        result.merge(
            search_space.check_setspace(
                self.availability_type, capability.availability_type
            ),
            "availability_type",
        )
        return result


class Availability(Feature):
    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_AVAILABILITY

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return AvailabilitySettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True


AvailabilitySetEnabled = partial(
    AvailabilitySettings,
    availability_type=search_space.SetSpace(True, [AvailabilityType.AvailabilitySet]),
)

AvailabilityZoneEnabled = partial(
    AvailabilitySettings,
    availability_type=search_space.SetSpace(True, [AvailabilityType.AvailabilityZone]),
)

AvailabilityTypeNoRedundancy = partial(
    AvailabilitySettings,
    availability_type=search_space.SetSpace(True, [AvailabilityType.NoRedundancy]),
)
