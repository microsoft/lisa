# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.case import TestCase
from unittest.mock import Mock, call, patch

from azure.core.exceptions import HttpResponseError, ODataV4Format
from msrestazure.azure_cloud import AZURE_PUBLIC_CLOUD

from lisa import schema
from lisa.environment import Environment
from lisa.sut_orchestrator.azure import platform_
from lisa.util import KernelPanicException, LisaException, RootFsMountFailedException
from lisa.util.logger import get_logger


class AzureSerialConsoleTestCase(TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self._environment = Mock(spec=Environment)
        self._environment.log_path = Path(directory.name)
        self._saved_log = (
            self._environment.log_path
            / "test_serial_log"
            / "test-vm_serial_console.log"
        )
        self._platform = platform_.AzurePlatform(schema.Platform())
        self._log = get_logger("test", "azure_serial_console")
        self._compute_client = Mock()
        self._compute_client.virtual_machines.list.return_value = [
            SimpleNamespace(name="test-vm")
        ]
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(
            patch.object(
                platform_, "get_compute_client", return_value=self._compute_client
            )
        )
        patches.enter_context(
            patch.object(platform_, "get_datetime_path", return_value="test")
        )
        self._save_console_log = patches.enter_context(
            patch.object(platform_, "save_console_log")
        )

    def test_serial_checks_receive_readable_text(self) -> None:
        cases = [
            (b"boot complete\n", "boot complete\n"),
            ("boot \u2713\n".encode("utf-8"), "boot \u2713\n"),
            (b"before\xe2after\xff\n", "before\ufffdafter\ufffd\n"),
            (b"truncated\xe2\x82", "truncated\ufffd"),
            (b"", ""),
        ]
        for content, expected in cases:
            with self.subTest(content=content):
                with patch.object(platform_, "check_panic") as check_panic:
                    with patch.object(
                        platform_, "check_rootfs_failure"
                    ) as check_rootfs:
                        self._capture_console(content)
                check_panic.assert_called_once_with(expected, "provision", self._log)
                check_rootfs.assert_called_once_with(expected, self._log)
                self.assertEqual(content, self._saved_log.read_bytes())

    def test_serial_collection_without_checks_preserves_invalid_bytes(self) -> None:
        content = b"unreadable\xff\xe2\x82"
        with patch.object(platform_, "check_panic") as check_panic:
            with patch.object(platform_, "check_rootfs_failure") as check_rootfs:
                self._capture_console(content, check_serial_console=False)
        check_panic.assert_not_called()
        check_rootfs.assert_not_called()
        self.assertEqual(content, self._saved_log.read_bytes())

    def test_invalid_utf8_does_not_hide_kernel_panic(self) -> None:
        content = b"\xff\nKernel panic - not syncing: test panic\n\xe2"
        with self.assertRaises(KernelPanicException):
            self._capture_console(content)
        self.assertEqual(content, self._saved_log.read_bytes())

    def test_invalid_utf8_does_not_hide_rootfs_failure(self) -> None:
        content = b"\xff\nALERT! UUID=test does not exist. Dropping to a shell!\n\xe2"
        with self.assertRaises(RootFsMountFailedException):
            self._capture_console(content)
        self.assertEqual(content, self._saved_log.read_bytes())

    def test_each_vm_has_its_own_serial_console(self) -> None:
        self._compute_client.virtual_machines.list.return_value = [
            SimpleNamespace(name="test-vm"),
            SimpleNamespace(name="second-vm"),
        ]
        self._save_console_log.side_effect = [b"first\xff", b"second\xfe"]
        with patch.object(platform_, "check_panic") as check_panic:
            with patch.object(platform_, "check_rootfs_failure") as check_rootfs:
                self._platform._save_console_log_and_check_panic(
                    "test-rg", self._environment, self._log, True
                )
        self.assertEqual(
            [
                call("first\ufffd", "provision", self._log),
                call("second\ufffd", "provision", self._log),
            ],
            check_panic.call_args_list,
        )
        self.assertEqual(
            [call("first\ufffd", self._log), call("second\ufffd", self._log)],
            check_rootfs.call_args_list,
        )
        self.assertEqual(b"first\xff", self._saved_log.read_bytes())
        self.assertEqual(
            b"second\xfe",
            (self._saved_log.parent / "second-vm_serial_console.log").read_bytes(),
        )

    def test_provisioning_timeout_is_not_masked_by_invalid_utf8(self) -> None:
        content = b"booting\xe2invalid\xff\n"
        with self.assertRaises(LisaException) as raised:
            self._deploy_with_console(content)
        self.assertEqual(
            "OSProvisioningTimedOut: OS Provisioning for VM 'test-vm' "
            "did not finish in the allotted time.",
            str(raised.exception),
        )
        self.assertIsInstance(raised.exception.__context__, HttpResponseError)
        self.assertEqual(content, self._saved_log.read_bytes())

    def test_provisioning_timeout_retains_detected_boot_failure(self) -> None:
        cases = [
            (
                b"\xff\nKernel panic - not syncing: test panic\n",
                "KernelPanicException",
            ),
            (
                b"\xff\nALERT! UUID=test does not exist. Dropping to a shell!\n",
                "RootFsMountFailedException",
            ),
        ]
        for content, exception_name in cases:
            with self.subTest(exception=exception_name):
                with self.assertRaisesRegex(
                    LisaException, f"OSProvisioningTimedOut: {exception_name}:"
                ):
                    self._deploy_with_console(content)
                self.assertEqual(content, self._saved_log.read_bytes())

    def _capture_console(
        self, content: bytes, check_serial_console: bool = True
    ) -> None:
        self._save_console_log.return_value = content
        self._platform._save_console_log_and_check_panic(
            "test-rg", self._environment, self._log, check_serial_console
        )

    def _deploy_with_console(self, content: bytes) -> None:
        self._save_console_log.return_value = content
        self._platform._azure_runbook = platform_.AzurePlatformSchema()
        self._platform.subscription_id = "00000000-0000-0000-0000-000000000000"
        self._platform.credential = Mock()
        self._platform.cloud = AZURE_PUBLIC_CLOUD
        deployment_error = HttpResponseError(message="DeploymentFailed")
        deployment_error.error = ODataV4Format(
            {
                "code": "OSProvisioningTimedOut",
                "message": (
                    "OS Provisioning for VM 'test-vm' did not finish "
                    "in the allotted time."
                ),
            }
        )
        with ExitStack() as patches:
            patches.enter_context(
                patch.object(self._platform, "_rm_client", create=True)
            )
            patches.enter_context(
                patch.object(
                    platform_.plugin_manager.hook, "azure_deploy_failed", create=True
                )
            )
            patches.enter_context(
                patch.object(platform_, "check_or_create_storage_account")
            )
            patches.enter_context(
                patch.object(platform_, "wait_operation", side_effect=deployment_error)
            )
            self._platform._deploy(
                "westus3",
                {platform_.AZURE_RG_NAME_KEY: "test-rg"},
                self._log,
                self._environment,
            )
