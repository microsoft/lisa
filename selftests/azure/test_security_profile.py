# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.case import TestCase
from unittest.mock import Mock

from marshmallow import ValidationError

from lisa import schema, search_space
from lisa.environment import Environment
from lisa.feature import reload_platform_features
from lisa.features.security_profile import SecurityProfileType
from lisa.sut_orchestrator.azure.common import AzureArmParameter, AzureNodeArmParameter
from lisa.sut_orchestrator.azure.features import (
    SecurityProfile,
    SecurityProfileSettings,
)
from lisa.util import NotMeetRequirementException, SkippedException


class AzureSecurityProfileTestCase(TestCase):
    def test_secure_boot_schema(self) -> None:
        for value, expected in [
            (None, None),
            (True, True),
            (False, False),
            ("false", False),
        ]:
            with self.subTest(value=value):
                settings = schema.load_by_type(
                    SecurityProfileSettings,
                    {"security_profile": "cvm", "secure_boot_enabled": value},
                )
                self.assertIs(settings.secure_boot_enabled, expected)

        with self.assertRaises(ValidationError):
            schema.load_by_type(
                SecurityProfileSettings, {"secure_boot_enabled": "invalid"}
            )

    def test_secure_boot_default_is_unspecified(self) -> None:
        settings = schema.load_by_type(SecurityProfileSettings, {})
        self.assertIsNone(settings.secure_boot_enabled)

    def test_secure_boot_is_part_of_feature_identity(self) -> None:
        enabled = SecurityProfileSettings(secure_boot_enabled=True)
        disabled = SecurityProfileSettings(secure_boot_enabled=False)
        self.assertNotEqual(enabled, disabled)
        self.assertEqual(2, len({enabled, disabled}))

    def test_requirement_matching_preserves_secure_boot(self) -> None:
        for method in ["choose_value", "intersect"]:
            for requirement, capability in [
                (False, None),
                (None, False),
                (False, False),
            ]:
                with self.subTest(
                    method=method, requirement=requirement, capability=capability
                ):
                    result = getattr(
                        SecurityProfileSettings(secure_boot_enabled=requirement),
                        method,
                    )(SecurityProfileSettings(secure_boot_enabled=capability))
                    self.assertIs(result.secure_boot_enabled, False)

    def test_conflicting_secure_boot_requirements_are_rejected(self) -> None:
        requirement = SecurityProfileSettings(secure_boot_enabled=True)
        capability = SecurityProfileSettings(secure_boot_enabled=False)
        self.assertFalse(requirement.check(capability).result)
        for method in ["choose_value", "intersect"]:
            with self.subTest(method=method):
                with self.assertRaisesRegex(
                    NotMeetRequirementException, "secure_boot_enabled"
                ):
                    getattr(requirement, method)(capability)

    def test_runbook_feature_reload_preserves_secure_boot(self) -> None:
        node = schema.load_by_type(
            schema.NodeSpace,
            {
                "features": {
                    "items": [
                        {
                            "type": "Security_Profile",
                            "security_profile": "cvm",
                            "encrypt_disk": False,
                            "secure_boot_enabled": False,
                        }
                    ]
                }
            },
        )
        reload_platform_features(node, [SecurityProfile])
        node_features = node.features
        self.assertIsNotNone(node_features)
        assert node_features is not None
        settings = next(iter(node_features))
        self.assertIsInstance(settings, SecurityProfileSettings)
        assert isinstance(settings, SecurityProfileSettings)
        self.assertIs(settings.secure_boot_enabled, False)
        chosen = settings.choose_value(SecurityProfileSettings())
        self.assertIs(chosen.secure_boot_enabled, False)

    def test_feature_merge_preserves_explicit_false_in_either_order(self) -> None:
        explicit = schema.load_by_type(
            schema.FeatureSettings,
            {
                "type": "Security_Profile",
                "security_profile": "cvm",
                "secure_boot_enabled": False,
            },
        )
        unspecified = schema.FeatureSettings(type="Security_Profile")
        for settings in [[explicit, unspecified], [unspecified, explicit]]:
            with self.subTest(settings=settings):
                node = schema.NodeSpace()
                node.features = search_space.SetSpace[schema.FeatureSettings](
                    items=settings
                )
                reload_platform_features(node, [SecurityProfile])
                node_features = node.features
                assert node_features is not None
                merged = next(iter(node_features))
                assert isinstance(merged, SecurityProfileSettings)
                self.assertIs(merged.secure_boot_enabled, False)

    def test_cvm_deployment_secure_boot_and_encryption(self) -> None:
        for secure_boot in [None, True, False]:
            for is_vhd in [False, True]:
                for encrypt_disk, des_id in [
                    (False, ""),
                    (True, ""),
                    (True, "test-des"),
                ]:
                    with self.subTest(
                        secure_boot=secure_boot,
                        is_vhd=is_vhd,
                        encrypt_disk=encrypt_disk,
                        des_id=des_id,
                    ):
                        parameters = self._deploy(
                            SecurityProfileType.CVM,
                            secure_boot,
                            is_vhd=is_vhd,
                            encrypt_disk=encrypt_disk,
                            des_id=des_id,
                        )
                        if is_vhd:
                            if encrypt_disk:
                                encryption = (
                                    "ConfidentialVM_DiskEncryptedWithCustomerKey"
                                    if des_id
                                    else "ConfidentialVM_DiskEncryptedWithPlatformKey"
                                )
                            else:
                                encryption = (
                                    "ConfidentialVM_"
                                    "VMGuestStateOnlyEncryptedWithPlatformKey"
                                )
                        else:
                            encryption = (
                                "DiskWithVMGuestState"
                                if encrypt_disk
                                else "VMGuestStateOnly"
                            )
                        self.assertEqual(
                            {
                                "secure_boot": secure_boot is not False,
                                "security_type": "ConfidentialVM",
                                "encryption_type": encryption,
                                "disk_encryption_set_id": des_id,
                            },
                            parameters.security_profile,
                        )
                        self.assertIs(
                            asdict(parameters)["security_profile"]["secure_boot"],
                            secure_boot is not False,
                        )

    def test_gallery_and_marketplace_images_disable_secure_boot(self) -> None:
        sources = [
            AzureNodeArmParameter(
                shared_gallery_raw={
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "resource_group_name": "test-rg",
                    "image_gallery": "test-gallery",
                    "image_definition": "test-image",
                    "image_version": "1.0.0",
                    "hyperv_generation": 2,
                }
            ),
            AzureNodeArmParameter(
                marketplace_raw={
                    "publisher": "test-publisher",
                    "offer": "test-offer",
                    "sku": "test-sku",
                    "version": "latest",
                    "hyperv_generation": 2,
                }
            ),
        ]
        for parameters in sources:
            with self.subTest(image=parameters.image):
                result = self._deploy(
                    SecurityProfileType.CVM, False, node_parameters=parameters
                )
                self.assertIs(result.security_profile["secure_boot"], False)
                self.assertEqual(
                    "VMGuestStateOnly", result.security_profile["encryption_type"]
                )

    def test_gen1_cvm_is_still_rejected(self) -> None:
        parameters = AzureNodeArmParameter(
            vhd_raw={
                "vhd_path": "https://example.invalid/gen1.vhd",
                "hyperv_generation": 1,
            }
        )
        with self.assertRaisesRegex(SkippedException, "gen2"):
            self._deploy(SecurityProfileType.CVM, False, node_parameters=parameters)

    def test_arm_template_preserves_vtpm_and_secure_boot_expression(self) -> None:
        template_path = (
            Path(__file__).resolve().parents[2]
            / "lisa"
            / "sut_orchestrator"
            / "azure"
            / "autogen_arm_template.json"
        )
        template = json.loads(template_path.read_text(encoding="utf-8"))
        security_profile = template["functions"][0]["members"][
            "generateSecurityProfile"
        ]["output"]["value"]
        self.assertIs(security_profile["uefiSettings"]["vTpmEnabled"], True)
        self.assertEqual(
            "[parameters('node').security_profile.secure_boot]",
            security_profile["uefiSettings"]["secureBootEnabled"],
        )

    def test_stateless_deployment_preserves_encryption(self) -> None:
        for secure_boot in [None, True, False]:
            for is_vhd in [False, True]:
                with self.subTest(secure_boot=secure_boot, is_vhd=is_vhd):
                    parameters = self._deploy(
                        SecurityProfileType.Stateless, secure_boot, is_vhd=is_vhd
                    )
                    self.assertEqual(
                        {
                            "secure_boot": secure_boot is not False,
                            "security_type": "ConfidentialVM",
                            "encryption_type": (
                                "ConfidentialVM_NonPersistedTPM"
                                if is_vhd
                                else "NonPersistedTPM"
                            ),
                            "disk_encryption_set_id": "",
                        },
                        parameters.security_profile,
                    )

    def test_non_cvm_profiles_are_unchanged(self) -> None:
        for secure_boot in [None, True, False]:
            for profile in [
                SecurityProfileType.Standard,
                SecurityProfileType.SecureBoot,
                SecurityProfileType.TrustedLaunchNoSecureBoot,
            ]:
                with self.subTest(secure_boot=secure_boot, profile=profile):
                    parameters = self._deploy(profile, secure_boot)
                    if profile == SecurityProfileType.Standard:
                        self.assertEqual({}, parameters.security_profile)
                    else:
                        self.assertEqual(
                            {
                                "secure_boot": profile
                                == SecurityProfileType.SecureBoot,
                                "security_type": "TrustedLaunch",
                                "encryption_type": "TrustedLaunch",
                                "disk_encryption_set_id": "",
                            },
                            parameters.security_profile,
                        )

    def _deploy(
        self,
        profile: SecurityProfileType,
        secure_boot: Optional[bool],
        is_vhd: bool = False,
        encrypt_disk: bool = False,
        des_id: str = "",
        node_parameters: Optional[AzureNodeArmParameter] = None,
    ) -> AzureNodeArmParameter:
        settings = SecurityProfileSettings(
            security_profile=profile,
            encrypt_disk=encrypt_disk,
            disk_encryption_set_id=des_id,
            secure_boot_enabled=secure_boot,
        )
        capability = schema.NodeSpace()
        capability.features = search_space.SetSpace[schema.FeatureSettings](
            items=[settings]
        )
        node = SimpleNamespace(capability=capability)
        environment = Mock(spec=Environment)
        environment.nodes = SimpleNamespace(_list=[node])
        parameters = (
            node_parameters if node_parameters is not None else AzureNodeArmParameter()
        )
        if is_vhd:
            parameters.vhd_raw = {
                "vhd_path": "https://example.invalid/image.vhd",
                "hyperv_generation": 2,
            }
        SecurityProfile.on_before_deployment(
            environment=environment,
            arm_parameters=AzureArmParameter(nodes=[parameters]),
        )
        return parameters
