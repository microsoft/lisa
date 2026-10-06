# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from types import SimpleNamespace
from unittest.case import TestCase
from unittest.mock import Mock

from lisa import search_space
from lisa.features.security_profile import SecurityProfileType
from lisa.sut_orchestrator.azure.common import (
    AzureArmParameter,
    AzureImageSchema,
    AzureNodeArmParameter,
)
from lisa.sut_orchestrator.azure.features import (
    SecurityProfile,
    SecurityProfileSettings,
)


class AzureSecurityProfileTestCase(TestCase):
    def test_lvbs_prod_unsigned_decodes(self) -> None:
        settings = SecurityProfileSettings.from_dict(
            {"security_profile": "lvbs-prod-unsigned"}
        )

        self.assertEqual(
            SecurityProfileType.LvbsProdUnsigned, settings.security_profile
        )

    def test_trusted_launch_image_supports_lvbs_prod_unsigned(self) -> None:
        image = AzureImageSchema()

        image._parse_security_profile(
            {"SecurityType": "TrustedLaunchSupported"}, Mock()
        )

        self.assertIsInstance(image.security_profile, search_space.SetSpace)
        self.assertIn(
            SecurityProfileType.LvbsProdUnsigned, image.security_profile.items
        )

    def test_trusted_launch_vm_size_supports_lvbs_prod_unsigned(self) -> None:
        settings = SecurityProfile.create_setting(
            raw_capabilities={
                "HyperVGenerations": "V1,V2",
                "TrustedLaunchDisabled": "False",
            },
            resource_sku=SimpleNamespace(family="standarddasv5family"),
        )

        self.assertIsInstance(settings, SecurityProfileSettings)
        self.assertIsInstance(settings.security_profile, search_space.SetSpace)
        self.assertIn(
            SecurityProfileType.LvbsProdUnsigned,
            settings.security_profile.items,
        )

    def test_lvbs_prod_unsigned_disables_secure_boot(self) -> None:
        settings = SecurityProfileSettings(
            security_profile=SecurityProfileType.LvbsProdUnsigned,
            encrypt_disk=False,
        )
        node = SimpleNamespace(
            capability=SimpleNamespace(features=SimpleNamespace(items=[settings]))
        )
        environment = SimpleNamespace(nodes=SimpleNamespace(_list=[node]))
        node_parameters = AzureNodeArmParameter()
        arm_parameters = AzureArmParameter(nodes=[node_parameters])

        SecurityProfile.on_before_deployment(
            environment=environment, arm_parameters=arm_parameters
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
        settings = SecurityProfileSettings(
            security_profile=SecurityProfileType.SecureBoot,
            encrypt_disk=False,
        )
        node = SimpleNamespace(
            capability=SimpleNamespace(features=SimpleNamespace(items=[settings]))
        )
        environment = SimpleNamespace(nodes=SimpleNamespace(_list=[node]))
        node_parameters = AzureNodeArmParameter()
        arm_parameters = AzureArmParameter(nodes=[node_parameters])

        SecurityProfile.on_before_deployment(
            environment=environment, arm_parameters=arm_parameters
        )

        self.assertTrue(node_parameters.security_profile["secure_boot"])
        self.assertEqual(
            "TrustedLaunch", node_parameters.security_profile["security_type"]
        )
