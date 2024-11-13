from dataclasses import dataclass
from typing import Any, Type, cast

from dataclasses_json import dataclass_json

from lisa import features, schema, search_space
from lisa.environment import Environment
from lisa.features.security_profile import SecurityProfileType
from lisa.sut_orchestrator.libvirt.context import GuestVmType, get_node_context


@dataclass_json()
@dataclass()
class SecurityProfileSettings(features.SecurityProfileSettings):
    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.security_profile}/"

    def _call_requirement_method(
        self, method: search_space.RequirementMethod, capability: Any
    ) -> Any:
        super_value: SecurityProfileSettings = super()._call_requirement_method(
            method, capability
        )
        value = SecurityProfileSettings()
        value.security_profile = super_value.security_profile
        return value


class SecurityProfile(features.SecurityProfile):
    _security_profile_mapping = {
        SecurityProfileType.Standard: GuestVmType.Standard,
        SecurityProfileType.CVM: GuestVmType.ConfidentialVM,
    }

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return SecurityProfileSettings

    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        environment = cast(Environment, kwargs.get("environment"))
        settings = kwargs.get("settings")
        if not settings:
            return
        for node in environment.nodes._list:
            assert isinstance(settings, SecurityProfileSettings)
            assert isinstance(settings.security_profile, SecurityProfileType)
            node_context = get_node_context(node)
            node_context.guest_vm_type = cls._security_profile_mapping[
                settings.security_profile
            ]
