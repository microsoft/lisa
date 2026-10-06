# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Dict, List, Optional, Tuple, Union
from unittest.case import TestCase
from unittest.mock import Mock

from azure.mgmt.compute.models import ResourceSku

from lisa import schema, search_space
from lisa.environment import Environment
from lisa.features.security_profile import CvmDisabled
from lisa.features.security_profile import (
    SecurityProfileSettings as BaseSecurityProfileSettings,
)
from lisa.features.security_profile import (
    SecurityProfileType,
    security_profile_priority,
)
from lisa.node import Node
from lisa.sut_orchestrator.azure.common import (
    AzureArmParameter,
    AzureImageSchema,
    AzureNodeArmParameter,
    AzureVmMarketplaceSchema,
    VhdSchema,
)
from lisa.sut_orchestrator.azure.features import (
    SecurityProfile,
    SecurityProfileSettings,
)
from lisa.util import NotMeetRequirementException, SkippedException


class AzureSecurityProfileTestCase(TestCase):
    def test_trusted_launch_no_secure_boot_decodes(self) -> None:
        settings = schema.load_by_type(
            SecurityProfileSettings, {"security_profile": "trustedlaunch-no-secureboot"}
        )
        self.assertEqual(
            SecurityProfileType.TrustedLaunchNoSecureBoot, settings.security_profile
        )
        self.assertEqual(
            "trustedlaunch-no-secureboot",
            SecurityProfileType.TrustedLaunchNoSecureBoot.value,
        )

    def test_removed_profile_value_is_rejected(self) -> None:
        for settings_type in [BaseSecurityProfileSettings, SecurityProfileSettings]:
            with self.subTest(settings_type=settings_type):
                with self.assertRaisesRegex(
                    ValueError, "is not a valid SecurityProfileType"
                ):
                    schema.load_by_type(
                        settings_type, {"security_profile": "lvbs-prod-unsigned"}
                    )

    def test_enum_preserves_existing_order(self) -> None:
        self.assertEqual(
            [
                SecurityProfileType.Standard,
                SecurityProfileType.CVM,
                SecurityProfileType.Stateless,
                SecurityProfileType.SecureBoot,
                SecurityProfileType.TrustedLaunchNoSecureBoot,
            ],
            list(SecurityProfileType),
        )

    def test_default_profiles_preserve_order(self) -> None:
        expected = [
            SecurityProfileType.Standard,
            SecurityProfileType.SecureBoot,
            SecurityProfileType.CVM,
            SecurityProfileType.Stateless,
            SecurityProfileType.TrustedLaunchNoSecureBoot,
        ]
        self.assertEqual(expected, security_profile_priority)
        for settings_type in [BaseSecurityProfileSettings, SecurityProfileSettings]:
            with self.subTest(settings_type=settings_type):
                self._assert_profile_order(settings_type().security_profile, expected)
                decoded: BaseSecurityProfileSettings = schema.load_by_type(
                    settings_type, {"security_profile": ""}
                )
                self._assert_profile_order(decoded.security_profile, expected)
        image = schema.load_by_type(AzureImageSchema, {"security_profile": ""})
        self._assert_profile_order(image.security_profile, expected)

    def test_non_cvm_profiles_preserve_order(self) -> None:
        self._assert_profile_order(
            CvmDisabled().security_profile,
            [
                SecurityProfileType.Standard,
                SecurityProfileType.SecureBoot,
                SecurityProfileType.TrustedLaunchNoSecureBoot,
            ],
        )

    def test_trusted_launch_image_supports_no_secure_boot(self) -> None:
        for security_type, os_type in [
            ("TrustedLaunchSupported", "Linux"),
            ("TrustedLaunch", "Linux"),
            ("TrustedLaunchAndConfidentialVmSupported", "Windows"),
        ]:
            with self.subTest(security_type=security_type, os_type=os_type):
                image = AzureImageSchema()
                image._parse_security_profile(
                    {"SecurityType": security_type, "os_type": os_type}, Mock()
                )
                requirement = SecurityProfile.create_image_requirement(image)
                self.assertIsNotNone(requirement)
                if not isinstance(requirement, SecurityProfileSettings):
                    self.fail("Expected Azure security profile settings")
                expected = [
                    SecurityProfileType.Standard,
                    SecurityProfileType.SecureBoot,
                ]
                if os_type == "Windows":
                    expected.extend(
                        [SecurityProfileType.CVM, SecurityProfileType.Stateless]
                    )
                expected.append(SecurityProfileType.TrustedLaunchNoSecureBoot)
                self._assert_profile_order(requirement.security_profile, expected)
                self.assertTrue(
                    SecurityProfileSettings(
                        security_profile=SecurityProfileType.TrustedLaunchNoSecureBoot
                    )
                    .check(requirement)
                    .result
                )

    def test_other_images_reject_trusted_launch_no_secure_boot(self) -> None:
        for security_type in [
            "",
            "TrustedLaunchAndConfidentialVmSupported",
            "ConfidentialVmSupported",
            "ConfidentialVM",
        ]:
            with self.subTest(security_type=security_type):
                image = AzureImageSchema()
                image._parse_security_profile(
                    {"SecurityType": security_type, "os_type": "Linux"}, Mock()
                )
                requirement = SecurityProfile.create_image_requirement(image)
                if not isinstance(requirement, SecurityProfileSettings):
                    self.fail("Expected Azure security profile settings")
                self.assertFalse(
                    SecurityProfileSettings(
                        security_profile=SecurityProfileType.TrustedLaunchNoSecureBoot
                    )
                    .check(requirement)
                    .result
                )

    def test_trusted_launch_vm_size_supports_no_secure_boot(self) -> None:
        settings = self._get_vm_size_settings(
            {"HyperVGenerations": "V1,V2", "TrustedLaunchDisabled": "False"}
        )
        requirement = SecurityProfileSettings(
            security_profile=SecurityProfileType.TrustedLaunchNoSecureBoot
        )
        selected = requirement.choose_value(settings)
        self.assertEqual(
            SecurityProfileType.TrustedLaunchNoSecureBoot, selected.security_profile
        )
        self.assertFalse(selected.encrypt_disk)

    def test_vm_size_profiles_preserve_order(self) -> None:
        cases: List[Tuple[str, List[SecurityProfileType]]] = [
            ("", []),
            ("snp", [SecurityProfileType.CVM]),
            ("tdx", [SecurityProfileType.CVM, SecurityProfileType.Stateless]),
        ]
        for cvm_type, cvm_profiles in cases:
            for generation in ["V1", "V2"]:
                with self.subTest(cvm_type=cvm_type, generation=generation):
                    settings = self._get_vm_size_settings(
                        {
                            "HyperVGenerations": generation,
                            "ConfidentialComputingType": cvm_type,
                        }
                    )
                    expected = [SecurityProfileType.Standard]
                    if generation == "V2":
                        expected.append(SecurityProfileType.SecureBoot)
                    expected.extend(cvm_profiles)
                    if generation == "V2":
                        expected.append(SecurityProfileType.TrustedLaunchNoSecureBoot)
                    self._assert_profile_order(settings.security_profile, expected)

    def test_unsupported_vm_sizes_reject_trusted_launch_no_secure_boot(self) -> None:
        for capabilities, family in [
            ({"HyperVGenerations": "V1"}, "standarddasv5family"),
            (
                {"HyperVGenerations": "V2", "TrustedLaunchDisabled": "True"},
                "standarddasv5family",
            ),
            ({"HyperVGenerations": "V2"}, "standardmsfamily"),
        ]:
            with self.subTest(capabilities=capabilities, family=family):
                settings = self._get_vm_size_settings(capabilities, family)
                requirement = SecurityProfileSettings(
                    security_profile=SecurityProfileType.TrustedLaunchNoSecureBoot
                )
                self.assertFalse(requirement.check(settings).result)
                with self.assertRaises(NotMeetRequirementException):
                    requirement.choose_value(settings)

    def test_existing_profiles_keep_selection_priority(self) -> None:
        for profile in [
            SecurityProfileType.Standard,
            SecurityProfileType.SecureBoot,
            SecurityProfileType.CVM,
            SecurityProfileType.Stateless,
        ]:
            with self.subTest(profile=profile):
                capability = BaseSecurityProfileSettings(
                    security_profile=search_space.SetSpace(
                        True, [profile, SecurityProfileType.TrustedLaunchNoSecureBoot]
                    )
                )
                selected = BaseSecurityProfileSettings().choose_value(capability)
                self.assertEqual(profile, selected.security_profile)

    def test_gueststate_vhd_defaults_to_secure_boot(self) -> None:
        image = VhdSchema(cvm_gueststate_path="gueststate.vmgs")
        image.load_from_platform(Mock())
        requirement = SecurityProfile.create_image_requirement(image)
        if not isinstance(requirement, SecurityProfileSettings):
            self.fail("Expected Azure security profile settings")
        capability = self._get_vm_size_settings({"HyperVGenerations": "V2"})
        selected = requirement.choose_value(capability)
        self.assertEqual(SecurityProfileType.SecureBoot, selected.security_profile)

    def test_vhd_supports_explicit_trusted_launch_no_secure_boot(self) -> None:
        for gueststate in [None, "gueststate.vmgs"]:
            with self.subTest(gueststate=gueststate):
                image = VhdSchema(cvm_gueststate_path=gueststate)
                image.load_from_platform(Mock())
                expected = (
                    [SecurityProfileType.CVM, SecurityProfileType.Stateless]
                    if gueststate
                    else [SecurityProfileType.Standard]
                )
                expected.extend(
                    [
                        SecurityProfileType.SecureBoot,
                        SecurityProfileType.TrustedLaunchNoSecureBoot,
                    ]
                )
                self._assert_profile_order(image.security_profile, expected)
                image_requirement = SecurityProfile.create_image_requirement(image)
                if not isinstance(image_requirement, SecurityProfileSettings):
                    self.fail("Expected Azure security profile settings")
                requirement = SecurityProfileSettings(
                    security_profile=SecurityProfileType.TrustedLaunchNoSecureBoot
                )
                combined = requirement.intersect(image_requirement)
                selected = combined.choose_value(
                    self._get_vm_size_settings({"HyperVGenerations": "V2"})
                )
                self.assertEqual(
                    SecurityProfileType.TrustedLaunchNoSecureBoot,
                    selected.security_profile,
                )

    def test_trusted_launch_no_secure_boot_disables_secure_boot(self) -> None:
        for vhd in [None, VhdSchema(vhd_path="image.vhd")]:
            with self.subTest(vhd=vhd):
                node_parameters = AzureNodeArmParameter()
                node_parameters.vhd = vhd
                self._configure_deployment(
                    SecurityProfileType.TrustedLaunchNoSecureBoot, node_parameters
                )
                self.assertEqual(
                    {
                        "secure_boot": False,
                        "security_type": "TrustedLaunch",
                        "encryption_type": "TrustedLaunch",
                        "disk_encryption_set_id": "",
                    },
                    node_parameters.security_profile,
                )

    def test_secure_boot_profile_remains_enabled(self) -> None:
        node_parameters = AzureNodeArmParameter()
        self._configure_deployment(SecurityProfileType.SecureBoot, node_parameters)
        self.assertTrue(node_parameters.security_profile["secure_boot"])
        self.assertEqual(
            "TrustedLaunch", node_parameters.security_profile["security_type"]
        )

    def test_standard_profile_remains_unconfigured(self) -> None:
        node_parameters = AzureNodeArmParameter()
        self._configure_deployment(SecurityProfileType.Standard, node_parameters)
        self.assertEqual({}, node_parameters.security_profile)

    def test_trusted_launch_no_secure_boot_rejects_gen1_image(self) -> None:
        node_parameters = AzureNodeArmParameter()
        node_parameters.marketplace = AzureVmMarketplaceSchema(hyperv_generation=1)
        with self.assertRaisesRegex(SkippedException, "can only be set on gen2"):
            self._configure_deployment(
                SecurityProfileType.TrustedLaunchNoSecureBoot, node_parameters
            )

    def _assert_profile_order(
        self,
        profiles: Optional[
            Union[search_space.SetSpace[SecurityProfileType], SecurityProfileType]
        ],
        expected: List[SecurityProfileType],
    ) -> None:
        if not isinstance(profiles, search_space.SetSpace):
            self.fail("Expected an ordered security profile capability")
        self.assertEqual(expected, profiles.items)

    def _get_vm_size_settings(
        self,
        capabilities: Dict[str, str],
        family: str = "standarddasv5family",
    ) -> SecurityProfileSettings:
        settings = SecurityProfile.create_setting(
            raw_capabilities=capabilities,
            resource_sku=ResourceSku.from_dict({"family": family}),
        )
        if not isinstance(settings, SecurityProfileSettings):
            self.fail("Expected Azure security profile settings")
        return settings

    def _configure_deployment(
        self,
        profile: SecurityProfileType,
        node_parameters: AzureNodeArmParameter,
    ) -> None:
        settings = SecurityProfileSettings(security_profile=profile, encrypt_disk=False)
        node = Mock(spec=Node)
        node.capability = schema.NodeSpace()
        node.capability.features = search_space.SetSpace(True, [settings])
        environment = Mock(spec=Environment)
        environment.nodes = Mock(_list=[node])
        arm_parameters = AzureArmParameter(nodes=[node_parameters])
        SecurityProfile.on_before_deployment(
            environment=environment, arm_parameters=arm_parameters
        )
