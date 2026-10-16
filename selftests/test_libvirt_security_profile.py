# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa import schema
from lisa.features.security_profile import SecurityProfileType
from lisa.util import NotMeetRequirementException

# Capability matching does not call the native libvirt APIs.
with patch.dict(sys.modules, {"libvirt": MagicMock(), "libvirtaio": MagicMock()}):
    from lisa.sut_orchestrator.libvirt.features import (
        SecurityProfile,
        SecurityProfileSettings,
    )
    from lisa.sut_orchestrator.libvirt.platform import (
        BaseLibvirtPlatform,
        _HostCapabilities,
    )


class LibvirtSecurityProfileTestCase(TestCase):
    def test_advertises_only_implemented_profiles(self) -> None:
        settings = self._get_security_profile_capability()
        for profile in SecurityProfileType:
            with self.subTest(profile=profile):
                requirement = SecurityProfileSettings(security_profile=profile)
                self.assertEqual(
                    profile in SecurityProfile._security_profile_mapping,
                    requirement.check(settings).result,
                )

    def test_rejects_trusted_launch_no_secure_boot_before_deployment(self) -> None:
        requirement = SecurityProfileSettings(
            security_profile=SecurityProfileType.TrustedLaunchNoSecureBoot
        )
        capability = self._get_security_profile_capability()
        self.assertFalse(requirement.check(capability).result)
        with self.assertRaises(NotMeetRequirementException):
            requirement.choose_value(capability)

    def test_supported_profiles_still_resolve(self) -> None:
        capability = self._get_security_profile_capability()
        for profile in [SecurityProfileType.Standard, SecurityProfileType.CVM]:
            with self.subTest(profile=profile):
                selected = SecurityProfileSettings(
                    security_profile=profile
                ).choose_value(capability)
                self.assertEqual(profile, selected.security_profile)

    def _get_security_profile_capability(self) -> SecurityProfileSettings:
        platform = BaseLibvirtPlatform(schema.Platform())
        host_capabilities = _HostCapabilities()
        host_capabilities.core_count = 2
        node_capabilities = platform._create_node_capabilities(host_capabilities)
        if node_capabilities.features is None:
            self.fail("Expected libvirt node features")
        for settings in node_capabilities.features.items:
            if isinstance(settings, SecurityProfileSettings):
                return settings
        raise AssertionError("Expected libvirt security profile capability")
