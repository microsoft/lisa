# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import Any, List, Type, Union

from dataclasses_json import dataclass_json

from lisa import schema, search_space
from lisa.feature import Feature
from lisa.util import constants, field_metadata

FEATURE_NAME_SECURITY_PROFILE = "Security_Profile"


class SecurityProfileType(str, Enum):
    Standard = constants.SECURITY_PROFILE_NONE
    CVM = constants.SECURITY_PROFILE_CVM
    Stateless = constants.SECURITY_PROFILE_STATELESS
    SecureBoot = constants.SECURITY_PROFILE_BOOT


security_profile_priority: List[SecurityProfileType] = [
    SecurityProfileType.Standard,
    SecurityProfileType.SecureBoot,
    SecurityProfileType.CVM,
    SecurityProfileType.Stateless,
]

encrypt_disk_priority: List[bool] = [False, True]


@dataclass_json()
@dataclass()
class SecurityProfileSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_SECURITY_PROFILE
    security_profile: Union[
        search_space.SetSpace[SecurityProfileType], SecurityProfileType
    ] = field(  # type:ignore
        default_factory=partial(
            search_space.SetSpace,
            items=[
                SecurityProfileType.Standard,
                SecurityProfileType.SecureBoot,
                SecurityProfileType.CVM,
                SecurityProfileType.Stateless,
            ],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_nullable_set_space,
                base_type=SecurityProfileType,
                default_values=[
                    SecurityProfileType.Standard,
                    SecurityProfileType.SecureBoot,
                    SecurityProfileType.CVM,
                    SecurityProfileType.Stateless,
                ],
            )
        ),
    )

    encrypt_disk: Union[search_space.SetSpace[bool], bool] = field(
        default_factory=partial(
            search_space.SetSpace[bool], is_allow_set=True, items=[False, True]
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_nullable_set_space,
                base_type=bool,
                default_values=[False, True],
            ),
            required=False,
        ),
    )

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.security_profile}/{self.encrypt_disk}"

    def _call_requirement_method(
        self, method: search_space.RequirementMethod, capability: Any
    ) -> Any:
        value = SecurityProfileSettings()
        value.security_profile = getattr(
            search_space, f"{method.value}_setspace_by_priority"
        )(
            self.security_profile,
            capability.security_profile,
            security_profile_priority,
        )
        value.encrypt_disk = getattr(
            search_space, f"{method.value}_setspace_by_priority"
        )(
            self.encrypt_disk,
            capability.encrypt_disk,
            encrypt_disk_priority,
        )
        return value

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, SecurityProfileSettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)
        result.merge(
            search_space.check_setspace(
                self.security_profile, capability.security_profile
            ),
            "security_profile",
        )
        result.merge(
            search_space.check_setspace(self.encrypt_disk, capability.encrypt_disk),
            "encrypt_disk",
        )
        return result


class SecurityProfile(Feature):
    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_SECURITY_PROFILE

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return SecurityProfileSettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True


SecureBootEnabled = partial(
    SecurityProfileSettings,
    security_profile=search_space.SetSpace(True, [SecurityProfileType.SecureBoot]),
    encrypt_disk=search_space.SetSpace(True, [False]),
)

CvmEnabled = partial(
    SecurityProfileSettings,
    security_profile=search_space.SetSpace(True, [SecurityProfileType.CVM]),
)

CvmDisabled = partial(
    SecurityProfileSettings,
    security_profile=search_space.SetSpace(
        True, [SecurityProfileType.Standard, SecurityProfileType.SecureBoot]
    ),
    encrypt_disk=search_space.SetSpace(True, [False]),
)

CvmDiskEncryptionEnabled = partial(
    SecurityProfileSettings,
    security_profile=search_space.SetSpace(True, [SecurityProfileType.CVM]),
    encrypt_disk=True,
)
