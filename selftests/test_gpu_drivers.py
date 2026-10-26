# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.operating_system import Ubuntu
from lisa.tools.gpu_drivers import NvidiaCudaDriver


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
