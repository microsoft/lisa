# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any, Dict

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import Cp, Ls, Md5sum, Reboot
from lisa.util import SkippedException
from microsoft.testsuites.mshv.cloud_hypervisor_tool import CloudHypervisor


@TestSuiteMetadata(
    area="mshv",
    category="functional",
    description="""
    This test suite is to test VM working well after updating Microsoft Hyper-V on VM
    and rebooting.
    """,
)
class MshvHostInstallSuite(TestSuite):
    CONFIG_BINPATH = "mshv_binpath"

    _test_path_init_hvix = Path("/home/cloud") / "hvix64.exe"

    _init_path_init_kdstub = Path("/home/cloud") / "kdstub.dll"

    _init_path_init_lxhvloader = Path("/home/cloud") / "lxhvloader.dll"

    _test_path_dst_hvix = Path("/boot/efi/Windows/System32") / "hvix64.exe"

    _test_path_dst_kdstub = Path("/boot/efi/Windows/System32") / "kdstub.dll"

    _test_path_dst_lxhvloader = Path("/boot/efi") / "lxhvloader.dll"

    @TestCaseMetadata(
        description="""
        This test case will
        1. Update to new MSHV components over old ones in a
            pre-configured MSHV image
        2. Reboot VM, check that mshv comes up

        The test expects the directory containing MSHV binaries to be passed in
        the mshv_binpath variable.
        """,
        priority=2,
    )
    def verify_mshv_install_succeeds(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
        log_path: Path,
    ) -> None:
        binpath = variables.get(self.CONFIG_BINPATH, "")
        if not binpath:
            raise SkippedException(
                "Requires a path to MSHV binaries to be passed via mshv_binpath"
            )

        test_hvix_file_path = Path(binpath) / "hvix64.exe"
        test_kdstub_file_path = Path(binpath) / "kdstub.dll"
        test_lxhvloader_file_path = Path(binpath) / "lxhvloader.dll"

        log.info(f"binpath: {binpath}")

        md5sum = node.tools[Md5sum]

        # === BEFORE: Capture checksums of existing binaries ===
        log.info("=== Capturing checksums of EXISTING binaries before replacement ===")
        old_hvix_md5 = md5sum.get_checksum(self._test_path_dst_hvix, sudo=True)
        old_kdstub_md5 = md5sum.get_checksum(self._test_path_dst_kdstub, sudo=True)
        old_lxhvloader_md5 = md5sum.get_checksum(
            self._test_path_dst_lxhvloader, sudo=True
        )
        log.info(f"BEFORE - hvix64.exe MD5: {old_hvix_md5}")
        log.info(f"BEFORE - kdstub.dll MD5: {old_kdstub_md5}")
        log.info(f"BEFORE - lxhvloader.dll MD5: {old_lxhvloader_md5}")

        # Copy Hvix64.exe, kdstub.dll, lxhvloader.dll into test machine
        copy_tool = node.tools[Cp]
        node.shell.copy(test_hvix_file_path, self._test_path_init_hvix)
        copy_tool.copy(self._test_path_init_hvix, self._test_path_dst_hvix, sudo=True)

        node.shell.copy(test_kdstub_file_path, self._init_path_init_kdstub)
        copy_tool.copy(
            self._init_path_init_kdstub, self._test_path_dst_kdstub, sudo=True
        )

        node.shell.copy(test_lxhvloader_file_path, self._init_path_init_lxhvloader)
        copy_tool.copy(
            self._init_path_init_lxhvloader, self._test_path_dst_lxhvloader, sudo=True
        )

        # === AFTER COPY: Verify new binaries are in place BEFORE reboot ===
        log.info(
            "=== Verifying NEW binaries are in place AFTER copy, BEFORE reboot ==="
        )
        new_hvix_md5_pre_reboot = md5sum.get_checksum(
            self._test_path_dst_hvix, sudo=True
        )
        new_kdstub_md5_pre_reboot = md5sum.get_checksum(
            self._test_path_dst_kdstub, sudo=True
        )
        new_lxhvloader_md5_pre_reboot = md5sum.get_checksum(
            self._test_path_dst_lxhvloader, sudo=True
        )
        log.info(f"AFTER COPY - hvix64.exe MD5: {new_hvix_md5_pre_reboot}")
        log.info(f"AFTER COPY - kdstub.dll MD5: {new_kdstub_md5_pre_reboot}")
        log.info(f"AFTER COPY - lxhvloader.dll MD5: {new_lxhvloader_md5_pre_reboot}")

        # Verify binaries were actually replaced
        assert old_hvix_md5 != new_hvix_md5_pre_reboot, (
            f"hvix64.exe was NOT replaced! "
            f"Old: {old_hvix_md5}, New: {new_hvix_md5_pre_reboot}"
        )
        assert old_kdstub_md5 != new_kdstub_md5_pre_reboot, (
            f"kdstub.dll was NOT replaced! "
            f"Old: {old_kdstub_md5}, New: {new_kdstub_md5_pre_reboot}"
        )
        assert old_lxhvloader_md5 != new_lxhvloader_md5_pre_reboot, (
            f"lxhvloader.dll was NOT replaced! "
            f"Old: {old_lxhvloader_md5}, New: {new_lxhvloader_md5_pre_reboot}"
        )
        log.info("✓ SUCCESS: All binaries were replaced with NEW versions")

        log.info("=== Rebooting system to load new MSHV binaries ===")
        node.tools[Reboot].reboot_and_check_panic(log_path)

        # === AFTER REBOOT: Verify binaries persisted after reboot ===
        log.info("=== Verifying NEW binaries are still in place AFTER reboot ===")
        new_hvix_md5_post_reboot = md5sum.get_checksum(
            self._test_path_dst_hvix, sudo=True
        )
        new_kdstub_md5_post_reboot = md5sum.get_checksum(
            self._test_path_dst_kdstub, sudo=True
        )
        new_lxhvloader_md5_post_reboot = md5sum.get_checksum(
            self._test_path_dst_lxhvloader, sudo=True
        )
        log.info(f"AFTER REBOOT - hvix64.exe MD5: {new_hvix_md5_post_reboot}")
        log.info(f"AFTER REBOOT - kdstub.dll MD5: {new_kdstub_md5_post_reboot}")
        log.info(f"AFTER REBOOT - lxhvloader.dll MD5: {new_lxhvloader_md5_post_reboot}")

        # Verify binaries persisted across reboot
        assert new_hvix_md5_pre_reboot == new_hvix_md5_post_reboot, (
            f"hvix64.exe changed after reboot! "
            f"Pre: {new_hvix_md5_pre_reboot}, Post: {new_hvix_md5_post_reboot}"
        )
        assert new_kdstub_md5_pre_reboot == new_kdstub_md5_post_reboot, (
            f"kdstub.dll changed after reboot! "
            f"Pre: {new_kdstub_md5_pre_reboot}, Post: {new_kdstub_md5_post_reboot}"
        )
        assert new_lxhvloader_md5_pre_reboot == new_lxhvloader_md5_post_reboot, (
            f"lxhvloader.dll changed after reboot! "
            f"Pre: {new_lxhvloader_md5_pre_reboot}, "
            f"Post: {new_lxhvloader_md5_post_reboot}"
        )
        log.info("✓ SUCCESS: New binaries persisted across reboot")

        node.tools[CloudHypervisor].save_dmesg_logs(node, log_path)

        # 2. check that mshv comes up
        mshv = node.tools[Ls].path_exists("/dev/mshv", sudo=True)
        assert (
            mshv
        ), "/dev/mshv not detected upon reboot. Check dmesg for mshv driver errors."
