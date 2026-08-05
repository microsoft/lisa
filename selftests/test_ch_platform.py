# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional, Tuple
from unittest import TestCase
from unittest.mock import MagicMock, patch

import libvirt

from lisa.sut_orchestrator.libvirt.ch_platform import (
    CH_DOMAIN_LOG_ARTIFACT_PREFIX,
    DOMAIN_START_ERROR_ARTIFACT_PREFIX,
    DOMAIN_START_EVIDENCE_ARTIFACT_PREFIX,
    DOMAIN_XML_ARTIFACT_PREFIX,
    CloudHypervisorPlatform,
)
from lisa.sut_orchestrator.libvirt.context import GuestVmType, NodeContext
from lisa.sut_orchestrator.libvirt.platform import BaseLibvirtPlatform
from lisa.tools import Chown, Cp, Ls, Whoami
from lisa.util import SkippedException

VM_NAME = "lisa-TEST-0"
DOMAIN_XML = f"<domain type='hyperv'><name>{VM_NAME}</name></domain>"
START_ERROR = "internal error: failed to boot guest VM"
EXACT_SIGNATURE_LOG = (
    "cloud-hypervisor: VmCreate(Kernel returned errno: "
    "Invalid argument (os error 22))\n"
)


class CloudHypervisorPlatformTestCase(TestCase):
    def _make_host_node(
        self,
        tmp: Path,
        ch_log_content: str,
        ch_log_exists: bool,
        chown_error: Optional[BaseException] = None,
    ) -> Any:
        """
        Build a mocked host node that emulates the per-domain CH log capture
        (Ls/Cp/Whoami/Chown tools + shell.copy_back + shell.remove).
        """
        ls_tool = MagicMock()
        ls_tool.path_exists.return_value = ch_log_exists
        cp_tool = MagicMock()
        whoami_tool = MagicMock()
        whoami_tool.get_username.return_value = "tester"
        chown_tool = MagicMock()
        if chown_error is not None:
            chown_tool.change_owner.side_effect = chown_error

        tools = {Ls: ls_tool, Cp: cp_tool, Whoami: whoami_tool, Chown: chown_tool}

        def copy_back(src: Any, dst: Any) -> None:
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_text(ch_log_content, encoding="utf-8")

        host_node = MagicMock()
        host_node.tools.__getitem__.side_effect = lambda key: tools[key]
        host_node.shell.copy_back.side_effect = copy_back
        host_node.working_path = tmp / "working"
        host_node.local_log_path = tmp / "hostlog"
        return host_node

    def _make_platform(self, host_node: Any) -> CloudHypervisorPlatform:
        platform = CloudHypervisorPlatform.__new__(CloudHypervisorPlatform)
        platform.host_node = host_node
        platform._log = MagicMock()
        platform.device_pool = MagicMock()
        # Deterministic runtime evidence for artifacts / skip reason.
        setattr(
            platform,
            "_get_vmm_version",
            MagicMock(return_value="cloud-hypervisor msft/v52.0.127"),
        )
        setattr(
            platform,
            "_get_host_kernel_version",
            MagicMock(return_value="6.18.34.mshv2"),
        )
        setattr(platform, "_get_libvirt_version", MagicMock(return_value="11.2.0"))
        return platform

    def _make_node_context(
        self,
        tmp: Path,
        guest_vm_type: GuestVmType,
        domain_active: bool,
        xml: str = DOMAIN_XML,
    ) -> NodeContext:
        node_context = NodeContext()
        node_context.vm_name = VM_NAME
        node_context.guest_vm_type = guest_vm_type
        node_context.console_log_file_path = str(tmp / "node-log" / "qemu-console.log")

        domain = MagicMock()
        domain.isActive.return_value = domain_active
        domain.XMLDesc.return_value = xml
        if not domain_active:
            # Domain exits during createWithFlags before it becomes active.
            domain.createWithFlags.side_effect = libvirt.libvirtError(START_ERROR)
        node_context.domain = domain
        return node_context

    def _start_and_capture(
        self,
        ch_log_content: str,
        ch_log_exists: bool = True,
        guest_vm_type: GuestVmType = GuestVmType.ConfidentialVM,
        domain_active: bool = False,
        console_attach_error: Optional[BaseException] = None,
        chown_error: Optional[BaseException] = None,
    ) -> Tuple[BaseException, Path, Any]:
        tmp_dir = TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        tmp = Path(tmp_dir.name)
        host_node = self._make_host_node(
            tmp, ch_log_content, ch_log_exists, chown_error
        )
        platform = self._make_platform(host_node)
        node_context = self._make_node_context(tmp, guest_vm_type, domain_active)
        node_log_dir = Path(node_context.console_log_file_path).parent

        # Console attach is not exercised by libvirt in unit tests.
        setattr(
            platform,
            "_attach_console_logger",
            MagicMock(side_effect=console_attach_error),
        )

        try:
            platform._create_domain_and_attach_logger(node_context)
        except BaseException as ex:  # noqa: B036
            return ex, node_log_dir, host_node
        raise AssertionError("Expected domain start to raise an exception.")

    def test_immediate_start_failure_preserves_all_artifacts(self) -> None:
        # A non-signature CVM start failure preserves CH log, domain XML,
        # evidence and error artifacts, removes the staged temp copy, and retains
        # the original failure (not a skip).
        ch_log = "cloud-hypervisor: starting\nunexpected diagnostic output\n"
        ex, node_log_dir, host_node = self._start_and_capture(ch_log)

        self.assertIsInstance(ex, libvirt.libvirtError)
        self.assertNotIsInstance(ex, SkippedException)

        ch_artifact = node_log_dir / f"{CH_DOMAIN_LOG_ARTIFACT_PREFIX}{VM_NAME}.log"
        self.assertTrue(ch_artifact.exists())
        self.assertEqual(ch_artifact.read_text(encoding="utf-8"), ch_log)

        xml_artifact = node_log_dir / f"{DOMAIN_XML_ARTIFACT_PREFIX}{VM_NAME}.xml"
        self.assertTrue(xml_artifact.exists())
        self.assertEqual(xml_artifact.read_text(encoding="utf-8"), DOMAIN_XML)

        evidence_artifact = (
            node_log_dir / f"{DOMAIN_START_EVIDENCE_ARTIFACT_PREFIX}{VM_NAME}.txt"
        )
        self.assertTrue(evidence_artifact.exists())
        evidence_text = evidence_artifact.read_text(encoding="utf-8")
        self.assertIn("msft/v52.0.127", evidence_text)
        self.assertIn("6.18.34.mshv2", evidence_text)
        self.assertIn("11.2.0", evidence_text)

        error_artifact = (
            node_log_dir / f"{DOMAIN_START_ERROR_ARTIFACT_PREFIX}{VM_NAME}.log"
        )
        self.assertTrue(error_artifact.exists())
        self.assertIn(START_ERROR, error_artifact.read_text(encoding="utf-8"))

        # The staged root-owned temp copy is removed after copy-back.
        host_node.shell.remove.assert_called_once_with(
            host_node.working_path / f"{VM_NAME}-ch.log"
        )

    def test_exact_vmcreate_einval_signature_is_cvm_skipped(self) -> None:
        # The exact captured CH signature on a CVM guest is classified as
        # unsupported, and the skip reason names artifacts and evidence.
        ex, node_log_dir, _ = self._start_and_capture(EXACT_SIGNATURE_LOG)

        self.assertIsInstance(ex, SkippedException)
        message = str(ex)
        self.assertIn("Confidential VM", message)
        self.assertIn("not supported", message)
        self.assertIn("VmCreate", message)
        self.assertIn(f"{CH_DOMAIN_LOG_ARTIFACT_PREFIX}{VM_NAME}.log", message)
        self.assertIn(f"{DOMAIN_XML_ARTIFACT_PREFIX}{VM_NAME}.xml", message)
        self.assertIn("msft/v52.0.127", message)

        ch_artifact = node_log_dir / f"{CH_DOMAIN_LOG_ARTIFACT_PREFIX}{VM_NAME}.log"
        self.assertTrue(ch_artifact.exists())

    def test_standard_guest_same_signature_stays_failure(self) -> None:
        # The same exact signature on a Standard (non-CVM) guest must re-raise the
        # original libvirt failure, not skip. Diagnostics are still preserved.
        ex, node_log_dir, _ = self._start_and_capture(
            EXACT_SIGNATURE_LOG, guest_vm_type=GuestVmType.Standard
        )

        self.assertIsInstance(ex, libvirt.libvirtError)
        self.assertNotIsInstance(ex, SkippedException)
        self.assertIn(START_ERROR, str(ex))

        ch_artifact = node_log_dir / f"{CH_DOMAIN_LOG_ARTIFACT_PREFIX}{VM_NAME}.log"
        self.assertTrue(ch_artifact.exists())

    def test_active_domain_console_failure_not_classified(self) -> None:
        # A failure raised after the domain is active (console attach/openConsole)
        # must not be treated as a start failure, even for a CVM guest with the
        # exact signature available: no skip, no diagnostics.
        console_error = libvirt.libvirtError("openConsole: operation failed")
        ex, node_log_dir, host_node = self._start_and_capture(
            EXACT_SIGNATURE_LOG,
            domain_active=True,
            console_attach_error=console_error,
        )

        self.assertIs(ex, console_error)
        self.assertNotIsInstance(ex, SkippedException)

        ch_artifact = node_log_dir / f"{CH_DOMAIN_LOG_ARTIFACT_PREFIX}{VM_NAME}.log"
        self.assertFalse(ch_artifact.exists())
        # No CH log staging/copy is attempted for an active-domain failure.
        host_node.shell.copy_back.assert_not_called()

    def test_near_miss_signature_stays_failure(self) -> None:
        # "VmCreate" with a different errno must NOT be classified as unsupported.
        ch_log = (
            "cloud-hypervisor: VmCreate(Kernel returned errno: "
            "Permission denied (os error 13))\n"
        )
        ex, _, _ = self._start_and_capture(ch_log)
        self.assertIsInstance(ex, libvirt.libvirtError)
        self.assertNotIsInstance(ex, SkippedException)

    def test_einval_without_vmcreate_stays_failure(self) -> None:
        # "Invalid argument" without a VmCreate failure is an unknown error.
        ch_log = "cloud-hypervisor: DeviceManager: Invalid argument (os error 22)\n"
        ex, _, _ = self._start_and_capture(ch_log)
        self.assertIsInstance(ex, libvirt.libvirtError)
        self.assertNotIsInstance(ex, SkippedException)

    def test_missing_ch_log_stays_failure_and_records_error(self) -> None:
        # When no CH log exists, the deployment error is retained and the
        # domain-start error/evidence/XML are still recorded for diagnostics.
        ex, node_log_dir, host_node = self._start_and_capture("", ch_log_exists=False)
        self.assertIsInstance(ex, libvirt.libvirtError)
        self.assertNotIsInstance(ex, SkippedException)

        self.assertTrue(
            (
                node_log_dir / f"{DOMAIN_START_ERROR_ARTIFACT_PREFIX}{VM_NAME}.log"
            ).exists()
        )
        self.assertTrue(
            (node_log_dir / f"{DOMAIN_XML_ARTIFACT_PREFIX}{VM_NAME}.xml").exists()
        )
        ch_artifact = node_log_dir / f"{CH_DOMAIN_LOG_ARTIFACT_PREFIX}{VM_NAME}.log"
        self.assertFalse(ch_artifact.exists())
        # No staging when the CH log does not exist.
        host_node.shell.remove.assert_not_called()

    def test_ch_log_command_assertion_error_does_not_mask_original(self) -> None:
        # LISA host tools (Cp/Chown) raise AssertionError on command failure.
        # This must be treated as an expected diagnostic failure: warn, preserve
        # the original libvirt error, and never skip. Even a CVM guest with the
        # exact signature stays a failure because the CH log could not be read.
        ex, node_log_dir, host_node = self._start_and_capture(
            EXACT_SIGNATURE_LOG,
            chown_error=AssertionError("chown command failed"),
        )

        self.assertIsInstance(ex, libvirt.libvirtError)
        self.assertNotIsInstance(ex, SkippedException)
        self.assertIn(START_ERROR, str(ex))

        # The CH log was not preserved (command failed) but the staged temp copy
        # is still cleaned up.
        ch_artifact = node_log_dir / f"{CH_DOMAIN_LOG_ARTIFACT_PREFIX}{VM_NAME}.log"
        self.assertFalse(ch_artifact.exists())
        host_node.shell.remove.assert_called_once_with(
            host_node.working_path / f"{VM_NAME}-ch.log"
        )

    def test_diagnostic_collection_failure_does_not_mask_original_error(self) -> None:
        # If diagnostic collection itself fails with an expected exception, the
        # original libvirt error must still be raised (never masked or skipped).
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            host_node = self._make_host_node(tmp, EXACT_SIGNATURE_LOG, True)
            platform = self._make_platform(host_node)
            node_context = self._make_node_context(
                tmp, GuestVmType.ConfidentialVM, domain_active=False
            )
            setattr(platform, "_attach_console_logger", MagicMock())
            preserve = MagicMock(side_effect=OSError("disk full"))
            setattr(platform, "_preserve_domain_start_diagnostics", preserve)

            with self.assertRaises(libvirt.libvirtError) as ctx:
                platform._create_domain_and_attach_logger(node_context)

            self.assertNotIsInstance(ctx.exception, SkippedException)
            self.assertIn(START_ERROR, str(ctx.exception))

    def test_delete_node_preserves_console_log_and_cleans_up(self) -> None:
        # Cleanup must remain reliable: the console log is preserved when present
        # and cleanup is always delegated to the base implementation.
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            node_log_dir = tmp / "node-log"
            node_log_dir.mkdir(parents=True)
            console_path = tmp / "qemu-console.log"
            console_path.write_text("console output", encoding="utf-8")

            node_context = NodeContext()
            node_context.vm_name = VM_NAME
            node_context.console_log_file_path = str(console_path)

            node = MagicMock()
            node.name = VM_NAME
            node.local_log_path = node_log_dir
            node.get_context.return_value = node_context

            platform = self._make_platform(MagicMock())
            log = MagicMock()

            with patch.object(BaseLibvirtPlatform, "_delete_node") as base_delete:
                platform._delete_node(node, log)

            base_delete.assert_called_once_with(node, log)
            self.assertTrue((node_log_dir / "ch-console.log").exists())

    def test_delete_node_cleans_up_when_console_copy_fails(self) -> None:
        # Even if console-log preservation fails, cleanup is still delegated.
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            node_context = NodeContext()
            node_context.vm_name = VM_NAME
            # Point at a non-existent file so preservation is skipped safely.
            node_context.console_log_file_path = str(tmp / "missing-console.log")

            node = MagicMock()
            node.name = VM_NAME
            node.local_log_path = tmp / "node-log"
            node.get_context.return_value = node_context

            platform = self._make_platform(MagicMock())
            log = MagicMock()

            with patch.object(BaseLibvirtPlatform, "_delete_node") as base_delete:
                platform._delete_node(node, log)

            base_delete.assert_called_once_with(node, log)
