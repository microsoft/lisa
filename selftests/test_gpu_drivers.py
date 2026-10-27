# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.base_tools import Uname
from lisa.microsoft.testsuites.gpu import gpusuite
from lisa.operating_system import Ubuntu
from lisa.tools.gpu_drivers import ComputeSDK, NvidiaCudaDriver
from lisa.tools.mokutil import Mokutil
from lisa.util import LisaException
from lisa.util.process import ExecutableResult


class NvidiaCudaDriverTestCase(TestCase):
    def setUp(self) -> None:
        self.driver = NvidiaCudaDriver.__new__(NvidiaCudaDriver)
        self.log = MagicMock()
        self.driver._log = self.log
        command_exists_patch = patch.object(
            self.driver, "command_exists", return_value=(True, False)
        )
        self.command_exists = command_exists_patch.start()
        self.addCleanup(command_exists_patch.stop)
        run_patch = patch.object(self.driver, "run")
        self.mock_run = run_patch.start()
        self.addCleanup(run_patch.stop)

    def test_incomplete_installation_is_not_detected_as_installed(self) -> None:
        for exit_code, stdout in (
            (9, "NVIDIA-SMI couldn't communicate with the NVIDIA driver."),
            (0, " \n"),
        ):
            with self.subTest(exit_code=exit_code, stdout=stdout):
                self.mock_run.return_value = MagicMock(
                    exit_code=exit_code, stdout=stdout, stderr="driver unavailable"
                )

                self.assertFalse(self.driver._check_exists())
                self.log.warning.assert_called()

    def test_working_driver_is_detected_without_installation(self) -> None:
        self.mock_run.return_value = MagicMock(
            exit_code=0, stdout="GPU 0: NVIDIA H100 (UUID: GPU-example)", stderr=""
        )

        self.assertTrue(self.driver._check_exists())
        self.mock_run.assert_called_once_with("-L", sudo=True, force_run=True)
        self.log.warning.assert_not_called()

    def test_missing_command_does_not_attempt_driver_query(self) -> None:
        self.command_exists.return_value = (False, False)

        self.assertFalse(self.driver._check_exists())
        self.mock_run.assert_not_called()

    def test_install_does_not_select_an_older_versioned_driver_branch(self) -> None:
        node = MagicMock()
        node.os = MagicMock(spec=Ubuntu)
        node.execute.return_value.stdout = (
            "cuda-drivers-580 - NVIDIA driver metapackage\n"
            "cuda-drivers - Transitional dummy package\n"
        )
        self.driver.node = node

        self.driver._install_cuda_debian_based("ubuntu2204")

        node.os.install_packages.assert_called_once_with("cuda-drivers")

    def test_secure_boot_selects_signed_modules_for_the_running_kernel(self) -> None:
        node = MagicMock()
        node.os = MagicMock(spec=Ubuntu)
        node.tools[
            Uname
        ].get_linux_information.return_value.kernel_version_raw = "6.8.0-1068-azure-fde"
        node.tools[Mokutil].is_secure_boot_enabled.return_value = True
        node.execute.side_effect = [
            MagicMock(
                stdout="nvidia-driver-595-server-open\nnvidia-driver-580-server-open"
            ),
            MagicMock(exit_code=100, stdout="", stderr="No packages found"),
            MagicMock(exit_code=0, stdout="Package: signed-modules", stderr=""),
        ]
        self.driver.node = node

        self.driver._install_cuda_ubuntu()

        self.assertEqual(
            node.os.install_packages.call_args_list,
            [
                call("ubuntu-drivers-common"),
                call(
                    [
                        "linux-modules-nvidia-580-server-open-6.8.0-1068-azure-fde",
                        "nvidia-headless-no-dkms-580-server-open",
                        "nvidia-utils-580-server",
                    ]
                ),
            ],
        )

    def test_secure_boot_does_not_fall_back_to_unsigned_modules(self) -> None:
        node = MagicMock()
        node.os = MagicMock(spec=Ubuntu)
        node.tools[
            Uname
        ].get_linux_information.return_value.kernel_version_raw = "6.8.0-custom"
        node.tools[Mokutil].is_secure_boot_enabled.return_value = True
        node.execute.side_effect = [
            MagicMock(stdout="nvidia-driver-580-server"),
            MagicMock(exit_code=100, stdout="", stderr="No packages found"),
        ]
        self.driver.node = node

        with self.assertRaisesRegex(LisaException, "6.8.0-custom"):
            self.driver._install_cuda_ubuntu()

        node.os.install_packages.assert_called_once_with("ubuntu-drivers-common")

    def test_secure_boot_disabled_preserves_cuda_repository_installation(self) -> None:
        node = MagicMock()
        node.os = MagicMock(spec=Ubuntu)
        node.os.information.version.major = 22
        node.os.information.version.minor = 4
        node.tools[Mokutil].is_secure_boot_enabled.return_value = False
        self.driver.node = node

        with patch.object(self.driver, "_install_cuda_debian_based") as install:
            self.driver._install_cuda_ubuntu()

        install.assert_called_once_with("ubuntu2204")

    def test_secure_boot_bypasses_extension_before_it_installs_unsigned_drivers(
        self,
    ) -> None:
        node = MagicMock()
        node.os = MagicMock(spec=Ubuntu)
        gpu_feature = node.features.__getitem__.return_value
        gpu_feature.is_module_loaded.return_value = False
        gpu_feature.get_supported_driver.return_value = ComputeSDK.CUDA
        node.tools[Mokutil].is_secure_boot_enabled.return_value = True
        log_path = Path("gpu-logs")
        log = MagicMock()

        with patch.object(gpusuite, "__install_driver_using_sdk") as install:
            gpusuite._install_driver(node, log_path, log)

        install.assert_called_once_with(node, log, log_path)
        gpu_feature._install_driver_using_platform_feature.assert_not_called()

    def test_other_installations_preserve_the_extension_path(self) -> None:
        for driver, secure_boot in (
            (ComputeSDK.CUDA, False),
            (ComputeSDK.GRID, True),
        ):
            with self.subTest(driver=driver, secure_boot=secure_boot):
                node = MagicMock()
                node.os = MagicMock(spec=Ubuntu)
                gpu_feature = node.features.__getitem__.return_value
                gpu_feature.is_module_loaded.return_value = False
                gpu_feature.get_supported_driver.return_value = driver
                node.tools[Mokutil].is_secure_boot_enabled.return_value = secure_boot

                with patch.object(gpusuite, "__install_driver_using_sdk") as install:
                    gpusuite._install_driver(node, Path("gpu-logs"), MagicMock())

                gpu_feature._install_driver_using_platform_feature.assert_called_once()
                install.assert_not_called()


class GpuSecureBootStateTestCase(TestCase):
    def test_legacy_bios_does_not_require_mokutil_efi_variables(self) -> None:
        tool = Mokutil.__new__(Mokutil)
        node = MagicMock()
        node.shell.exists.return_value = False
        tool.node = node

        with patch.object(tool, "run") as mock_run:
            self.assertFalse(tool.is_secure_boot_enabled())

        mock_run.assert_not_called()

    def test_failed_or_unrecognized_query_is_not_treated_as_disabled(self) -> None:
        tool = Mokutil.__new__(Mokutil)
        tool.node = MagicMock()
        for exit_code, stdout, stderr, error in (
            (1, "", "Permission denied", AssertionError),
            (0, "Unknown state", "", LisaException),
        ):
            with self.subTest(exit_code=exit_code):
                result = ExecutableResult(
                    stdout, stderr, exit_code, "mokutil --sb-state", "test", 0
                )
                with patch.object(tool, "run", return_value=result):
                    with self.assertRaises(error):
                        tool.is_secure_boot_enabled()
