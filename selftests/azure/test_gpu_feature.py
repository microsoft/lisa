# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from inspect import unwrap
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from azure.core.exceptions import HttpResponseError

from lisa.features import Gpu as BaseGpu
from lisa.microsoft.testsuites.gpu.gpusuite import GpuTestSuite, _install_driver
from lisa.operating_system import OsInformation, Ubuntu
from lisa.sut_orchestrator.azure.features import AzureExtension, Gpu
from lisa.util import (
    LisaException,
    SkippedException,
    UnsupportedOperationException,
    parse_version,
)


class AzureGpuFeatureTestCase(TestCase):
    _unsupported_os = (
        "[NGDL-readJSON-9001] Driver selection failed: OS offer='ubuntu' "
        "sku='20.04' is not supported for category='CUDA' driverVersion='Latest'"
    )

    def setUp(self) -> None:
        self.os = Ubuntu.__new__(Ubuntu)
        self.os._information = OsInformation(
            version=parse_version("20.04"), vendor="Ubuntu", release="20.04"
        )
        self.node = MagicMock(os=self.os)
        self.extension = MagicMock()
        self.gpu = Gpu.__new__(Gpu)
        self.gpu._node = self.node
        self.gpu._log = MagicMock()
        self.node.features.__getitem__.side_effect = {
            AzureExtension: self.extension,
            BaseGpu: self.gpu,
        }.__getitem__

    def _unsupported_error(self) -> HttpResponseError:
        return HttpResponseError(
            message=(
                "(VMExtensionProvisioningError) VM has reported a failure: "
                "[NGDL-nvidia-vmext-9003] Failed to read configuration settings "
                "(readJSON exit code 1). Root cause: " + self._unsupported_os
            )
        )

    def test_explicit_unsupported_os_preserves_reason_and_cause(self) -> None:
        error = self._unsupported_error()
        self.extension.create_or_update.side_effect = error

        with self.assertRaises(UnsupportedOperationException) as context:
            self.gpu._install_driver_using_platform_feature()

        self.assertEqual(self._unsupported_os, str(context.exception))
        self.assertIs(error, context.exception.__cause__)
        self.node.close.assert_not_called()

    def test_other_extension_failures_are_not_skipped(self) -> None:
        messages = [
            "[NGDL-readJSON-9001] Driver selection failed: GPU is not supported",
            "[NGDL-readJSON-9001] Driver selection failed: invalid driverVersion",
            "[NGDL-nvidia-vmext-9003] Failed to read configuration settings",
            "DKMS build failed",
            "Authorization failed",
            self._unsupported_os.replace("NGDL-readJSON-9001", "unknown-error"),
        ]
        for message in messages:
            with self.subTest(message=message):
                error = HttpResponseError(message=message)
                self.extension.create_or_update.side_effect = error

                with self.assertRaises(HttpResponseError) as context:
                    self.gpu._install_driver_using_platform_feature()

                self.assertIs(error, context.exception)

    def test_non_http_error_is_not_reclassified(self) -> None:
        error = LisaException(self._unsupported_os)
        self.extension.create_or_update.side_effect = error

        with self.assertRaises(LisaException) as context:
            self.gpu._install_driver_using_platform_feature()

        self.assertIs(error, context.exception)

    def test_successful_focal_and_newer_installs_are_unchanged(self) -> None:
        self.extension.create_or_update.return_value = {
            "provisioning_state": "Succeeded"
        }
        for release in ["20.04", "22.04", "24.04"]:
            with self.subTest(release=release):
                self.os.information.release = release
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

    def test_failed_provisioning_state_remains_failure(self) -> None:
        self.extension.create_or_update.return_value = {"provisioning_state": "Failed"}

        with self.assertRaisesRegex(LisaException, "GPU Extension Provisioning Failed"):
            self.gpu._install_driver_using_platform_feature()

    def test_case_skips_with_specific_extension_reason(self) -> None:
        self.extension.create_or_update.side_effect = self._unsupported_error()
        suite_type = unwrap(GpuTestSuite)
        suite = suite_type.__new__(suite_type)

        with self.assertRaises(SkippedException) as context:
            suite.verify_gpu_extension_installation(
                node=self.node, log_path=Path("."), log=MagicMock()
            )

        self.assertIn(self._unsupported_os, str(context.exception))
        self.node.tools.__getitem__.assert_not_called()

    def test_general_install_keeps_manual_fallback(self) -> None:
        self.extension.create_or_update.side_effect = self._unsupported_error()
        log = MagicMock()
        with patch.object(self.gpu, "is_module_loaded", return_value=False), patch(
            "lisa.microsoft.testsuites.gpu.gpusuite.__install_driver_using_sdk"
        ) as install_sdk:
            _install_driver(self.node, Path("."), log)

        install_sdk.assert_called_once_with(self.node, log, Path("."))
        self.assertIn(self._unsupported_os, log.info.call_args.args[0])
