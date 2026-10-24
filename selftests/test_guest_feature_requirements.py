# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any, Dict, Type, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa import schema
from lisa.environment import EnvironmentSpace
from lisa.feature import Feature
from lisa.features.security_profile import (
    SecurityProfile,
    SecurityProfileSettings,
    SecurityProfileType,
)
from lisa.microsoft.testsuites.core.kvp import Kvp
from lisa.microsoft.testsuites.core.provisioning import Provisioning
from lisa.microsoft.testsuites.vm_extensions.mdm import MetricsExtension
from lisa.node import LocalNode, RemoteNode
from lisa.operating_system import OsInformation, Ubuntu
from lisa.sut_orchestrator import AZURE, HYPERV, OPENVMM, READY
from lisa.sut_orchestrator.openvmm.node import OpenVmmGuestNode
from lisa.sut_orchestrator.openvmm.schema import (
    OpenVmmGuestNodeSchema,
    OpenVmmUefiSchema,
)
from lisa.testsuite import TestCaseRuntimeData, TestResult, get_cases_metadata
from lisa.tools import Cat, GrubConfig, KernelConfig, Lsblk, Sed, Service
from lisa.tools.lsblk import DiskInfo
from lisa.util import LisaException, SkippedException, parse_version


class GuestFeatureRequirementTestCase(TestCase):
    def setUp(self) -> None:
        provisioning_class = cast(Any, Provisioning).__wrapped__
        self.provisioning = object.__new__(provisioning_class)
        kvp_class = cast(Any, Kvp).__wrapped__
        self.kvp = object.__new__(kvp_class)
        self.node = MagicMock(spec=RemoteNode)
        self.node.os = MagicMock(spec=Ubuntu)
        self.node.features = MagicMock()
        self.features: Dict[Type[Feature], MagicMock] = {}
        self.node.features.__getitem__.side_effect = self.features.__getitem__
        self.node.features.is_supported.side_effect = (
            lambda feature_type: feature_type in self.features
        )
        self.node.tools = MagicMock()
        self.log = MagicMock()
        self.cat = MagicMock(spec=Cat)
        self.grub = MagicMock(spec=GrubConfig)
        self.kernel = MagicMock(spec=KernelConfig)
        self.kernel.is_enabled.return_value = True
        self.lsblk = MagicMock(spec=Lsblk)
        self.tools = {
            Cat: self.cat,
            GrubConfig: self.grub,
            KernelConfig: self.kernel,
            Lsblk: self.lsblk,
        }
        self.node.tools.__getitem__.side_effect = self.tools.__getitem__
        smoke_patch = patch.object(self.provisioning, "_smoke_test")
        self.smoke = smoke_patch.start()
        self.addCleanup(smoke_patch.stop)

    def test_swiotlb_requirement_matches_actual_isolated_guest(self) -> None:
        host = LocalNode(schema.LocalNode(), index=0, logger_name="host")
        guest = OpenVmmGuestNode(
            OpenVmmGuestNodeSchema(
                use_parent_capability=False,
                uefi=OpenVmmUefiSchema(firmware_path="firmware.fd"),
                disk_img="guest.img",
            ),
            index=0,
            logger_name="guest",
            parent=host,
        )
        requirement = get_cases_metadata()[
            "Provisioning.verify_deployment_provision_swiotlb_force"
        ].requirement
        assert requirement and requirement.environment
        result = requirement.environment.check(
            EnvironmentSpace(nodes=[guest.capability])
        )

        self.assertTrue(result.result, result.reasons)

    def test_swiotlb_uses_guest_disk_without_cloud_features(self) -> None:
        for disk_name, argument in (
            ("vda", "force"),
            ("sda", "force"),
            ("nvme0n1", "force,524288"),
        ):
            with self.subTest(disk=disk_name):
                self.grub.reset_mock()
                self.node.reboot.reset_mock()
                self.lsblk.find_disk_by_mountpoint.return_value = DiskInfo(
                    disk_name, "/"
                )
                self.cat.read.return_value = f"root=UUID=example swiotlb={argument}"

                self.provisioning.verify_deployment_provision_swiotlb_force(
                    log=self.log, node=self.node, log_path=Path("case")
                )

                self.grub.set_kernel_cmdline_arg.assert_called_once_with(
                    "swiotlb", argument
                )
                self.node.reboot.assert_called_once()
                self.node.mark_dirty.assert_called()

    def test_confidential_or_encrypted_profiles_stay_excluded(self) -> None:
        for profile_type, encrypted in (
            (SecurityProfileType.CVM, False),
            (SecurityProfileType.Stateless, False),
            (SecurityProfileType.Standard, True),
        ):
            profile = MagicMock(spec=SecurityProfile)
            profile.get_settings.return_value = SecurityProfileSettings(
                security_profile=profile_type, encrypt_disk=encrypted
            )
            self.features[SecurityProfile] = profile
            for case in (
                self.kvp.verify_kvp,
                self.provisioning.verify_deployment_provision_swiotlb_force,
            ):
                with self.subTest(profile=profile_type, encrypted=encrypted, case=case):
                    self.node.tools.reset_mock()
                    with self.assertRaises(SkippedException):
                        case(log=self.log, node=self.node, log_path=Path("case"))

                    self.node.tools.__getitem__.assert_not_called()

    def test_grub_access_failure_is_not_misreported_as_na(self) -> None:
        def get_tool(tool: Type[Any]) -> MagicMock:
            if tool is GrubConfig:
                raise LisaException("GRUB access failed")
            return self.tools[tool]

        self.node.tools.__getitem__.side_effect = get_tool

        with self.assertRaisesRegex(LisaException, "GRUB access failed") as context:
            self.provisioning.verify_deployment_provision_swiotlb_force(
                log=self.log, node=self.node, log_path=Path("case")
            )

        self.assertNotIsInstance(context.exception, SkippedException)
        self.node.reboot.assert_not_called()

    def test_kvp_qualification_requires_a_host_metadata_platform(self) -> None:
        result = TestResult(
            "kvp", TestCaseRuntimeData(get_cases_metadata()["Kvp.verify_kvp"])
        )

        self.assertFalse(result.check_platform(OPENVMM).result)
        for platform in (AZURE, HYPERV, READY):
            with self.subTest(platform=platform):
                self.assertTrue(result.check_platform(platform).result)

    def _configure_metrics_case(self, release: str) -> None:
        metrics_class = cast(Any, MetricsExtension).__wrapped__
        self.metrics = object.__new__(metrics_class)
        self.node.os = object.__new__(Ubuntu)
        self.node.os._information = OsInformation(
            version=parse_version(release),
            vendor="Ubuntu",
            release=release,
            full_version=f"Ubuntu {release} LTS",
        )
        self.metrics_methods: Dict[str, MagicMock] = {}
        for name in (
            "add_azure_core_repo",
            "package_exists",
            "is_package_in_repo",
            "install_packages",
            "uninstall_packages",
        ):
            method_patch = patch.object(self.node.os, name)
            self.metrics_methods[name] = method_patch.start()
            self.addCleanup(method_patch.stop)
        self.metrics_methods["package_exists"].return_value = False
        self.metrics_methods["is_package_in_repo"].return_value = True
        self.metrics_service = MagicMock(spec=Service)
        self.metrics_service.check_service_status.return_value = True
        self.tools.update({Sed: MagicMock(spec=Sed), Service: self.metrics_service})

    def test_metrics_jammy_reaches_install_start_and_uninstall(self) -> None:
        self._configure_metrics_case("22.04")

        self.metrics.verify_metricsextension(node=self.node, log=self.log)

        self.metrics_methods["add_azure_core_repo"].assert_called_once()
        self.metrics_methods["install_packages"].assert_called_once_with("metricsext2")
        self.metrics_service.restart_service.assert_called_once_with("mdm")
        self.metrics_service.check_service_status.assert_called_once_with("mdm")
        self.metrics_methods["uninstall_packages"].assert_called_once_with(
            "metricsext2"
        )

    def test_metrics_unknown_release_skips_before_environment_changes(self) -> None:
        self._configure_metrics_case("99.04")

        with self.assertRaises(SkippedException):
            self.metrics.verify_metricsextension(node=self.node, log=self.log)

        self.metrics_methods["add_azure_core_repo"].assert_not_called()
        self.metrics_methods["install_packages"].assert_not_called()
        self.metrics_service.restart_service.assert_not_called()
