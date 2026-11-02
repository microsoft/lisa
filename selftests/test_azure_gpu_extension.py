# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from azure.core.exceptions import HttpResponseError

from lisa.features import Gpu as GpuFeature
from lisa.microsoft.testsuites.gpu import gpusuite
from lisa.operating_system import Redhat, Ubuntu
from lisa.sut_orchestrator.azure.features import AzureExtension, Gpu
from lisa.util import LisaException, SkippedException, UnsupportedOperationException


class AzureGpuExtensionTestCase(TestCase):
    def setUp(self) -> None:
        self.node = MagicMock()
        self.os = Ubuntu.__new__(Ubuntu)
        self.os._information = Mock(release="22.04")
        self.node.os = self.os
        self.extension = Mock()
        self.extension.create_or_update.return_value = {
            "provisioning_state": "Succeeded"
        }
        self.gpu = Gpu.__new__(Gpu)
        self.gpu._node = self.node
        self.gpu._log = Mock()
        self.node.features = {AzureExtension: self.extension, GpuFeature: self.gpu}
        self.case = getattr(
            gpusuite.GpuTestSuite, "__wrapped__"
        ).verify_gpu_extension_installation

    def test_ubuntu_2004_rejected_before_extension_creation(self) -> None:
        self.os._information.release = "20.04"
        with self.assertRaisesRegex(UnsupportedOperationException, "Ubuntu 20.04"):
            self.gpu._install_driver_using_platform_feature()
        self.extension.create_or_update.assert_not_called()
        self.node.close.assert_not_called()

    def test_supported_ubuntu_releases_keep_default_extension_settings(self) -> None:
        for release in ["22.04", "24.04"]:
            with self.subTest(release=release):
                self.os._information.release = release
                self.extension.reset_mock()
                self.node.close.reset_mock()
                self.gpu._install_driver_using_platform_feature()
                self.extension.create_or_update.assert_called_once_with(
                    type_="NvidiaGpuDriverLinux",
                    publisher="Microsoft.HpcCompute",
                    auto_upgrade_minor_version=True,
                    settings={},
                    type_handler_version="1.8",
                )
                self.node.close.assert_called_once_with()

    def test_provisioning_exception_is_not_converted_to_skip(self) -> None:
        failure = HttpResponseError(message="extension installation failed")
        self.extension.create_or_update.side_effect = failure
        with self.assertRaises(HttpResponseError) as raised:
            self.gpu._install_driver_using_platform_feature()
        self.assertIs(failure, raised.exception)

    def test_existing_redhat_support_and_rhui_handling_are_preserved(self) -> None:
        for release in ["7.9", "8.2"]:
            with self.subTest(release=release):
                redhat = Redhat.__new__(Redhat)
                redhat._information = Mock(release=release)
                self.node.os = redhat
                self.extension.reset_mock()
                with patch.object(redhat, "handle_rhui_issue") as rhui:
                    self.gpu._install_driver_using_platform_feature()
                rhui.assert_called_once_with()
                self.extension.create_or_update.assert_called_once()

    def test_failed_provisioning_state_remains_failure(self) -> None:
        self.extension.create_or_update.return_value = {"provisioning_state": "Failed"}
        with self.assertRaisesRegex(LisaException, "GPU Extension Provisioning Failed"):
            self.gpu._install_driver_using_platform_feature()

    def test_testcase_skips_ubuntu_2004_with_os_context(self) -> None:
        self.os._information.release = "20.04"
        with self.assertRaisesRegex(SkippedException, "Ubuntu 20.04"):
            self.case(Mock(), self.node, Path("."), Mock())
        self.extension.create_or_update.assert_not_called()
        self.node.tools.__getitem__.assert_not_called()

    def test_testcase_does_not_skip_real_extension_failures(self) -> None:
        self.extension.create_or_update.side_effect = HttpResponseError(
            message="extension installation failed"
        )
        with self.assertRaises(HttpResponseError):
            self.case(Mock(), self.node, Path("."), Mock())
        self.node.tools.__getitem__.assert_not_called()
