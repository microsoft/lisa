# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any, Dict

from microsoft.testsuites.mshv.cloud_hypervisor_tool import CloudHypervisor

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import Cp, Ls, Reboot
from lisa.util import SkippedException


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

    def _get_file_md5(self, node: Node, file_path: Path) -> str:
        """Get MD5 checksum of a file on the remote node."""
        result = node.execute(f"md5sum {file_path}", sudo=True, shell=True)
        if result.exit_code != 0:
            raise AssertionError(f"Failed to get MD5 for {file_path}: {result.stderr}")
        # md5sum output format: "checksum  filename"
        md5_parts = result.stdout.split()
        if not md5_parts:
            raise AssertionError(
                f"Invalid md5sum output for {file_path}: {result.stdout}"
            )
        return md5_parts[0]

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

        # Check if existing binaries exist before getting checksums
        ls_tool = node.tools[Ls]
        if not ls_tool.path_exists(str(self._test_path_dst_hvix), sudo=True):
            raise SkippedException(
                "MSHV binaries not found - requires pre-configured MSHV image"
            )

        # === BEFORE: Capture checksums of existing binaries ===
        old_hvix_md5 = self._get_file_md5(node, self._test_path_dst_hvix)
        old_kdstub_md5 = self._get_file_md5(node, self._test_path_dst_kdstub)
        old_lxhvloader_md5 = self._get_file_md5(node, self._test_path_dst_lxhvloader)
        log.debug(f"Existing Binaries - hvix64.exe MD5: {old_hvix_md5}")
        log.debug(f"Existing Binaries - kdstub.dll MD5: {old_kdstub_md5}")
        log.debug(f"Existing Binaries - lxhvloader.dll MD5: {old_lxhvloader_md5}")

        # Copy Hvix64.exe, kdstub.dll, lxhvloader.dll into test machine
        copy_tool = node.tools[Cp]
        node.shell.copy(test_hvix_file_path, self._test_path_init_hvix)
        node.shell.copy(test_kdstub_file_path, self._init_path_init_kdstub)
        node.shell.copy(test_lxhvloader_file_path, self._init_path_init_lxhvloader)

        # Check if source binaries are different from destination before copying
        src_hvix_md5 = self._get_file_md5(node, self._test_path_init_hvix)
        src_kdstub_md5 = self._get_file_md5(node, self._init_path_init_kdstub)
        src_lxhvloader_md5 = self._get_file_md5(node, self._init_path_init_lxhvloader)
        log.debug(f"Source Binaries - hvix64.exe MD5: {src_hvix_md5}")
        log.debug(f"Source Binaries - kdstub.dll MD5: {src_kdstub_md5}")
        log.debug(f"Source Binaries - lxhvloader.dll MD5: {src_lxhvloader_md5}")

        # If all source binaries match destination, skip the test
        if (
            src_hvix_md5 == old_hvix_md5
            and src_kdstub_md5 == old_kdstub_md5
            and src_lxhvloader_md5 == old_lxhvloader_md5
        ):
            raise SkippedException(
                "Source MSHV binaries are identical to already-installed versions. "
                "Test requires different binaries to validate install/reboot process. "
                f"hvix64.exe: {src_hvix_md5}, kdstub.dll: {src_kdstub_md5}, "
                f"lxhvloader.dll: {src_lxhvloader_md5}"
            )

        log.info("Source binaries differ - proceeding with installation test")

        # Now perform the actual copy to destination
        copy_tool.copy(self._test_path_init_hvix, self._test_path_dst_hvix, sudo=True)
        copy_tool.copy(
            self._init_path_init_kdstub, self._test_path_dst_kdstub, sudo=True
        )
        copy_tool.copy(
            self._init_path_init_lxhvloader, self._test_path_dst_lxhvloader, sudo=True
        )

        # === AFTER COPY: Verify new binaries are in place BEFORE reboot ===
        new_hvix_md5_pre_reboot = self._get_file_md5(node, self._test_path_dst_hvix)
        new_kdstub_md5_pre_reboot = self._get_file_md5(node, self._test_path_dst_kdstub)
        new_lxhvloader_md5_pre_reboot = self._get_file_md5(
            node, self._test_path_dst_lxhvloader
        )

        # Verify binaries were actually replaced (should match source now)
        assert new_hvix_md5_pre_reboot == src_hvix_md5, (
            f"hvix64.exe copy failed! "
            f"Expected: {src_hvix_md5}, Got: {new_hvix_md5_pre_reboot}"
        )
        assert new_kdstub_md5_pre_reboot == src_kdstub_md5, (
            f"kdstub.dll copy failed! "
            f"Expected: {src_kdstub_md5}, Got: {new_kdstub_md5_pre_reboot}"
        )
        assert new_lxhvloader_md5_pre_reboot == src_lxhvloader_md5, (
            f"lxhvloader.dll copy failed! "
            f"Expected: {src_lxhvloader_md5}, Got: {new_lxhvloader_md5_pre_reboot}"
        )
        log.info("SUCCESS: All binaries were replaced with NEW versions")

        log.info("=== Rebooting system to load new MSHV binaries ===")
        node.tools[Reboot].reboot_and_check_panic(log_path)

        # === AFTER REBOOT: Verify binaries persisted after reboot ===
        new_hvix_md5_post_reboot = self._get_file_md5(node, self._test_path_dst_hvix)
        new_kdstub_md5_post_reboot = self._get_file_md5(
            node, self._test_path_dst_kdstub
        )
        new_lxhvloader_md5_post_reboot = self._get_file_md5(
            node, self._test_path_dst_lxhvloader
        )
        log.debug(f"After Reboot - hvix64.exe MD5: {new_hvix_md5_post_reboot}")
        log.debug(f"After Reboot - kdstub.dll MD5: {new_kdstub_md5_post_reboot}")
        log.debug(
            f"After Reboot - lxhvloader.dll MD5: {new_lxhvloader_md5_post_reboot}"
        )

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
        log.info("SUCCESS: New binaries persisted across reboot")

        ch_tool: CloudHypervisor = node.tools[CloudHypervisor]
        ch_tool.save_dmesg_logs(node, log_path)

        # 2. check that mshv comes up
        mshv = node.tools[Ls].path_exists("/dev/mshv", sudo=True)
        assert (
            mshv
        ), "/dev/mshv not detected upon reboot. Check dmesg for mshv driver errors."
