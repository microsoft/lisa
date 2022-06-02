# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass
from functools import partial
from typing import Any, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema, search_space
from lisa.feature import Feature

FEATURE_NAME_SECURITY_PROFILE = "Security_Profile"


@dataclass_json()
@dataclass()
class SecurityProfileSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_SECURITY_PROFILE
    secure_boot_enabled: bool = False

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.secure_boot_enabled}"

    def _generate_min_capability(self, capability: Any) -> Any:
        return self

    def check(self, capability: Any) -> search_space.ResultReason:
        result = super().check(capability)

        result.merge(
            search_space.check_countspace(
                self.secure_boot_enabled, capability.secure_boot_enabled
            ),
            "secure_boot_enabled",
        )
        return result


class SecurityProfile(Feature):
    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        settings = cast(SecurityProfileSettings, kwargs.get("settings"))
        if settings.secure_boot_enabled:
            cls._enable_secure_boot(*args, **kwargs)

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_SECURITY_PROFILE

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return SecurityProfileSettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    @classmethod
    def _enable_secure_boot(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    def enabled(self) -> bool:
        return True


SecureBootEnabled = partial(SecurityProfileSettings, secure_boot_enabled=True)
