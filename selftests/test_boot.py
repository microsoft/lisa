# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.microsoft.testsuites.core.boot import Boot
from lisa.operating_system import CentOs, Redhat, Ubuntu
from lisa.tools import Reboot, Uname
from lisa.util import SkippedException, constants


class DebugKernelBootTestCase(TestCase):
    def setUp(self) -> None:
        suite_type = unwrap(Boot)
        self.suite = suite_type.__new__(suite_type)
        self.node = MagicMock()
        self.node.os = MagicMock(spec=Redhat)
        self.node.os.is_package_in_repo.return_value = True
        self.debug_kernel = "/boot/vmlinuz-5.14.0-70.101.1.el9_0.x86_64+debug"
        self.node.execute.side_effect = [
            SimpleNamespace(stdout=self.debug_kernel),
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout=self.debug_kernel),
        ]
        self.reboot = MagicMock()
        self.uname = MagicMock()
        self.uname.get_linux_information.return_value = SimpleNamespace(
            kernel_version_raw=Path(self.debug_kernel).name[len("vmlinuz-") :]
        )
        self.node.tools = {Reboot: self.reboot, Uname: self.uname}
        self.node.connection_info = {
            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS: "192.0.2.1",
            constants.ENVIRONMENTS_NODES_REMOTE_PORT: 22,
        }
        self.log = MagicMock()
        self.log_path = Path("boot-test")
        self.ready = patch(
            "lisa.microsoft.testsuites.core.boot.wait_tcp_port_ready",
            return_value=(True, 0),
        )
        self.ready.start()
        self.addCleanup(self.ready.stop)

    def _run_test(self) -> None:
        self.suite.verify_boot_with_debug_kernel(
            log=self.log, node=self.node, log_path=self.log_path
        )

    def test_selects_debug_kernel_by_path_instead_of_menu_index(self) -> None:
        self._run_test()

        self.node.os.install_packages.assert_called_once_with(
            ["kernel-debug", "grubby"]
        )
        self.node.mark_dirty.assert_called_once()
        self.assertEqual(
            [
                call(
                    "ls -1v /boot/vmlinuz-*debug",
                    shell=True,
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "Could not list installed debug kernels"
                    ),
                ),
                call(
                    f"grubby --set-default={self.debug_kernel}",
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "Could not select the debug kernel"
                    ),
                ),
                call(
                    "grubby --default-kernel",
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "Could not read the default kernel"
                    ),
                ),
            ],
            self.node.execute.call_args_list,
        )
        self.reboot.reboot_and_check_panic.assert_called_once_with(self.log_path)
        self.uname.get_linux_information.assert_called_once_with(force_run=True)

    def test_selects_newest_of_version_sorted_debug_kernels(self) -> None:
        older = "/boot/vmlinuz-5.14.0-70.9.1.el9_0.x86_64+debug"
        newer = "/boot/vmlinuz-5.14.0-70.10.1.el9_0.x86_64+debug"
        self.node.execute.side_effect = [
            SimpleNamespace(stdout=f"{older}\n{newer}\n"),
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout=newer),
        ]

        self._run_test()

        self.assertEqual(
            self.node.execute.call_args_list[1].args[0],
            f"grubby --set-default={newer}",
        )

    def test_empty_kernel_listing_fails_before_reboot(self) -> None:
        self.node.execute.side_effect = [SimpleNamespace(stdout="")]

        with self.assertRaisesRegex(AssertionError, "No debug kernel image found"):
            self._run_test()

        self.assertEqual(self.node.execute.call_count, 1)
        self.reboot.reboot_and_check_panic.assert_not_called()

    def test_command_failures_abort_before_reboot(self) -> None:
        results = [
            SimpleNamespace(stdout=self.debug_kernel),
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout=self.debug_kernel),
        ]
        for failed_command in range(3):
            with self.subTest(failed_command=failed_command):
                self.node.execute.reset_mock()
                self.node.execute.side_effect = results[:failed_command] + [
                    AssertionError("Command failed")
                ]
                with self.assertRaisesRegex(AssertionError, "Command failed"):
                    self._run_test()
                self.assertEqual(self.node.execute.call_count, failed_command + 1)
                self.reboot.reboot_and_check_panic.assert_not_called()

    def test_wrong_grub_default_fails_before_reboot(self) -> None:
        self.node.execute.side_effect = [
            SimpleNamespace(stdout=self.debug_kernel),
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout=self.debug_kernel.replace("+debug", "")),
        ]

        with self.assertRaisesRegex(AssertionError, "GRUB default does not match"):
            self._run_test()

        self.reboot.reboot_and_check_panic.assert_not_called()

    def test_normal_kernel_after_reboot_still_fails(self) -> None:
        self.uname.get_linux_information.return_value = SimpleNamespace(
            kernel_version_raw="5.14.0-70.101.1.el9_0.x86_64"
        )

        with self.assertRaisesRegex(AssertionError, "Kernel version is not debug"):
            self._run_test()

        self.reboot.reboot_and_check_panic.assert_called_once_with(self.log_path)

    def test_centos_remains_supported(self) -> None:
        self.node.os = MagicMock(spec=CentOs)
        self.node.os.is_package_in_repo.return_value = True

        self._run_test()

        self.reboot.reboot_and_check_panic.assert_called_once_with(self.log_path)

    def test_unsupported_distro_is_skipped(self) -> None:
        self.node.os = MagicMock(spec=Ubuntu)

        with self.assertRaises(SkippedException):
            self._run_test()

        self.node.mark_dirty.assert_not_called()
        self.node.execute.assert_not_called()

    def test_unavailable_debug_package_is_skipped(self) -> None:
        self.node.os.is_package_in_repo.return_value = False

        with self.assertRaises(SkippedException):
            self._run_test()

        self.node.mark_dirty.assert_not_called()
        self.node.os.install_packages.assert_not_called()
        self.node.execute.assert_not_called()
