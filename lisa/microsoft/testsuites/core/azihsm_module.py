# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import re
import time
from dataclasses import dataclass

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Uname, Wget
from lisa.operating_system import CBLMariner
from lisa.tools import Dmesg, Lsmod, Modinfo, Modprobe
from lisa.util import LisaException, SkippedException


@dataclass
class RpmMetadata:
    """Metadata parsed from the RPM package file."""

    version: str  # e.g. "3.2.0"
    release: str  # e.g. "1_6.12.57.1.2.azl3"
    target_kernel: str  # e.g. "6.12.57.1-2.azl3"
    module_name: str  # e.g. "azihsm"
    module_file: str  # e.g. "/lib/modules/6.12.57.1-2.azl3/extra/azihsm.ko"


@TestSuiteMetadata(
    area="kernel",
    category="driver",
    description="""
    Test suite for the manticore-hwe RPM package containing the azihsm
    kernel module.  Validates RPM installation, kernel module loading
    behaviour, and clean uninstallation.

    Mirrors the checks in test_manticore_hwe.sh (18 tests, 3 phases).
    All version and kernel information is parsed from the RPM itself.

    Supports two modes:
    - Local RPM: set LISA_RPM_PATH to the RPM file path on the node.
    - Source tarball: set LISA_OOT_SOURCE_URL to a URL pointing to a
      tarball that contains pre-built RPMs (e.g. manticore.tar.gz).
      The tarball is downloaded, extracted, and the RPM found inside.
    """,
    requirement=simple_requirement(
        min_core_count=2,
        min_memory_mb=4096,
        supported_os=[CBLMariner],
    ),
)
class AziHsmRpmTest(TestSuite):
    """Tests for the manticore-hwe RPM packaging of the azihsm driver."""

    PKG_NAME = "manticore-hwe"
    _DOWNLOAD_DIR = "/tmp/azihsm-download"
    _EXTRACT_DIR = "/tmp/azihsm-extracted"

    # ── helpers ────────────────────────────────────────────────────────

    def _get_source_url(self) -> str:
        """Get the OOT source URL from environment.

        Set via:
            export LISA_OOT_SOURCE_URL=https://example.com/manticore.tar.gz
        """
        return os.environ.get("LISA_OOT_SOURCE_URL", "")

    def _download_and_extract_rpm(
        self, node: Node, log: Logger, source_url: str
    ) -> str:
        """Download a tarball from *source_url*, extract it, and return
        the path to the first ``manticore-hwe-*.rpm`` found inside.

        Expected tarball layout::

            RPMS/x86_64/manticore-hwe-<ver>.rpm
        """
        log.info(f"Downloading source tarball from: {source_url}")

        node.execute(
            f"rm -rf {self._DOWNLOAD_DIR} {self._EXTRACT_DIR} && "
            f"mkdir -p {self._DOWNLOAD_DIR} {self._EXTRACT_DIR}",
            sudo=True,
            shell=True,
        )

        filename = source_url.rsplit("/", 1)[-1]

        # Download
        wget = node.tools[Wget]
        download_path = wget.get(
            url=source_url,
            file_path=self._DOWNLOAD_DIR,
            filename=filename,
            sudo=True,
        )
        log.info(f"Downloaded {filename}")

        # Determine tar flags from extension
        if filename.endswith((".tar.gz", ".tgz")):
            tar_flags = "-xzf"
        elif filename.endswith((".tar.bz2", ".tbz2")):
            tar_flags = "-xjf"
        elif filename.endswith(".tar"):
            tar_flags = "-xf"
        else:
            # Try plain tar (file may be mis-named)
            tar_flags = "-xf"

        result = node.execute(
            f"tar {tar_flags} {download_path} -C {self._EXTRACT_DIR}",
            sudo=True,
            shell=True,
            timeout=120,
        )
        if result.exit_code != 0:
            # Retry with plain -xf (covers mis-named .tar.gz that is raw tar)
            log.info("Retrying extract with plain tar -xf")
            result = node.execute(
                f"tar -xf {download_path} -C {self._EXTRACT_DIR}",
                sudo=True,
                shell=True,
                timeout=120,
            )
            if result.exit_code != 0:
                raise LisaException(
                    f"Failed to extract {filename}: "
                    f"{result.stderr or result.stdout}"
                )

        log.info(f"Extracted tarball to {self._EXTRACT_DIR}")

        # Locate the RPM inside the extracted tree
        result = node.execute(
            f"find {self._EXTRACT_DIR} -name '{self.PKG_NAME}-*.rpm' "
            f"-type f | head -1",
            sudo=True,
            shell=True,
        )
        rpm_path = result.stdout.strip()
        if not rpm_path:
            # Show what was extracted for debugging
            result = node.execute(
                f"find {self._EXTRACT_DIR} -type f", sudo=True
            )
            log.warning(f"Extracted files:\n{result.stdout}")
            raise LisaException(
                f"No {self.PKG_NAME}-*.rpm found in tarball from {source_url}"
            )

        log.info(f"Found RPM in tarball: {rpm_path}")
        return rpm_path

    def _get_rpm_path(self, node: Node, log: Logger) -> str:
        """Locate the RPM on the remote node.

        Search order:
        1. LISA_OOT_SOURCE_URL — download tarball and extract the RPM.
        2. LISA_RPM_PATH — explicit path to an RPM already on the node.
        3. Glob search: /tmp/manticore-hwe-*.rpm
        4. Glob search: /home/*/manticore-hwe-*.rpm
        """
        # 1. Source tarball URL
        source_url = self._get_source_url()
        if source_url:
            return self._download_and_extract_rpm(node, log, source_url)

        # 2. Explicit RPM path
        env_path = os.environ.get("LISA_RPM_PATH", "")
        if env_path:
            result = node.execute(
                f"test -f {env_path}", sudo=True, no_error_log=True
            )
            if result.exit_code == 0:
                log.info(f"RPM found via LISA_RPM_PATH: {env_path}")
                return env_path

        # 3 & 4. Glob search
        search_patterns = [
            f"/tmp/{self.PKG_NAME}-*.rpm",
            f"/home/*/{self.PKG_NAME}-*.rpm",
        ]

        for pattern in search_patterns:
            result = node.execute(
                f"ls {pattern} 2>/dev/null | head -1",
                sudo=True,
                shell=True,
                no_error_log=True,
            )
            if result.exit_code == 0 and result.stdout.strip():
                path = result.stdout.strip()
                log.info(f"RPM found at: {path}")
                return path

        raise SkippedException(
            f"RPM not found on node. Searched: {search_patterns}. "
            "Set LISA_OOT_SOURCE_URL (tarball URL) or LISA_RPM_PATH."
        )

    def _parse_rpm_metadata(
        self, node: Node, log: Logger, rpm_path: str
    ) -> RpmMetadata:
        """Parse version, release, target kernel, and module info from RPM."""

        # Get VERSION and RELEASE from the RPM
        result = node.execute(
            f"rpm -qp --queryformat '%{{VERSION}} %{{RELEASE}}' {rpm_path}",
            sudo=True,
        )
        if result.exit_code != 0:
            raise LisaException(
                f"Failed to query RPM metadata: {result.stderr}"
            )
        parts = result.stdout.strip().split()
        if len(parts) != 2:
            raise LisaException(
                f"Unexpected rpm query output: '{result.stdout.strip()}'"
            )
        version, release = parts[0], parts[1]
        log.info(f"RPM version={version}, release={release}")

        # Find the .ko file path inside the RPM to get target kernel
        result = node.execute(
            f"rpm -qpl {rpm_path} | grep '\\.ko$'",
            sudo=True,
            shell=True,
        )
        if result.exit_code != 0 or not result.stdout.strip():
            raise LisaException(
                f"No .ko file found in RPM: {result.stderr}"
            )

        ko_path = result.stdout.strip().splitlines()[0]
        log.info(f"Module file in RPM: {ko_path}")

        # Parse target kernel from path: /lib/modules/<kernel>/extra/<name>.ko
        match = re.match(
            r"/lib/modules/([^/]+)/.*?/([^/]+)\.ko$", ko_path
        )
        if not match:
            raise LisaException(
                f"Cannot parse kernel version from module path: {ko_path}"
            )

        target_kernel = match.group(1)
        module_name = match.group(2)
        log.info(
            f"Parsed: target_kernel={target_kernel}, module={module_name}"
        )

        return RpmMetadata(
            version=version,
            release=release,
            target_kernel=target_kernel,
            module_name=module_name,
            module_file=ko_path,
        )

    def _modules_dep(self, target_kernel: str) -> str:
        return f"/lib/modules/{target_kernel}/modules.dep"

    def _extra_dir(self, target_kernel: str) -> str:
        return f"/lib/modules/{target_kernel}/extra/"

    def _ensure_clean_state(
        self, node: Node, log: Logger, module_name: str
    ) -> None:
        """Unload module and remove package so we start clean."""
        modprobe = node.tools[Modprobe]
        if modprobe.is_module_loaded(
            module_name, force_run=True, no_error_log=True
        ):
            log.info("Module loaded - removing before test")
            modprobe.remove([module_name], ignore_error=True)

        result = node.execute(
            f"rpm -q {self.PKG_NAME}", sudo=True, no_error_log=True
        )
        if result.exit_code == 0:
            log.info("Package installed - removing before test")
            node.execute(
                f"rpm -e {self.PKG_NAME}", sudo=True, no_error_log=True
            )

    def _install_rpm(
        self, node: Node, log: Logger, rpm_path: str
    ) -> None:
        # Validate RPM file first
        result = node.execute(
            f"rpm -qp '{rpm_path}'", sudo=True, no_error_log=True
        )
        assert_that(result.exit_code).described_as(
            f"{rpm_path} must be a valid RPM"
        ).is_equal_to(0)

        # Use node.execute directly to avoid Tool caching --
        # Tool.run() caches results and silently skips re-installs.
        result = node.execute(
            f"rpm -ivh '{rpm_path}'", sudo=True, shell=True
        )
        assert_that(result.exit_code).described_as(
            f"rpm -ivh must succeed for {rpm_path}"
        ).is_equal_to(0)
        log.info("RPM installed successfully")

    def _uninstall_rpm(self, node: Node, log: Logger) -> None:
        # Unload module first if loaded (pre-uninstall safety)
        node.execute(
            "modprobe -r azihsm", sudo=True, no_error_log=True
        )
        node.execute(
            f"rpm -evh {self.PKG_NAME}", sudo=True, no_error_log=True
        )
        log.info("RPM removed")

    def _install_kernel_hwe_if_needed(
        self, node: Node, log: Logger, target_kernel: str
    ) -> None:
        """Install the kernel-hwe package and reboot if the running
        kernel does not match *target_kernel*.

        After reboot the running kernel is verified.  If there is still
        a mismatch the test is skipped.
        """
        uname = node.tools[Uname]
        info = uname.get_linux_information()
        running = info.kernel_version_raw
        if running == target_kernel:
            log.info(f"Running kernel already matches target: {running}")
            return

        log.info(
            f"Kernel mismatch: running={running}, target={target_kernel}. "
            "Attempting to install kernel-hwe and reboot."
        )

        hwe_pkg = os.environ.get("LISA_KERNEL_HWE_PACKAGE", "kernel-hwe")
        result = node.execute(
            f"tdnf install -y {hwe_pkg}", sudo=True, timeout=600
        )
        if result.exit_code != 0:
            raise SkippedException(
                f"Failed to install {hwe_pkg}: {result.stderr}. "
                f"Running kernel ({running}) != target ({target_kernel})."
            )
        log.info(f"Installed {hwe_pkg}, rebooting node")

        node.reboot(time_out=600)

        # Re-check after reboot
        info = uname.get_linux_information(force_run=True)
        running = info.kernel_version_raw
        if running != target_kernel:
            raise SkippedException(
                f"After kernel-hwe install + reboot, running kernel "
                f"({running}) still != target ({target_kernel})"
            )
        log.info(f"After reboot, running kernel matches: {running}")

    def _skip_if_kernel_mismatch(
        self, node: Node, log: Logger, target_kernel: str
    ) -> str:
        """Ensure the running kernel matches *target_kernel*.

        Tries to install kernel-hwe and reboot first.  Falls back to
        SkippedException if the kernel still does not match.

        Returns the running kernel string on match.
        """
        self._install_kernel_hwe_if_needed(node, log, target_kernel)

        uname = node.tools[Uname]
        info = uname.get_linux_information(force_run=True)
        return info.kernel_version_raw

    # ── Phase 1: Installation (tests 1-5) ──────────────────────────────

    @TestCaseMetadata(
        description="""
        Phase 1 - Installation.
        1. RPM installs without errors.
        2a. Package registered in RPM database.
        2b. Package version matches expected version.
        3. Module .ko file exists on disk.
        4. rpm -V reports no discrepancies.
        5. depmod registered the module in modules.dep.
        """,
        priority=1,
    )
    def verify_azihsm_rpm_installation(
        self, node: Node, log: Logger
    ) -> None:
        rpm_path = self._get_rpm_path(node, log)
        meta = self._parse_rpm_metadata(node, log, rpm_path)
        dep_file = self._modules_dep(meta.target_kernel)

        self._ensure_clean_state(node, log, meta.module_name)

        # Test 1 - RPM installs without errors
        self._install_rpm(node, log, rpm_path)

        # Test 2a - package in RPM database
        result = node.execute(
            f"rpm -q {self.PKG_NAME}",
            sudo=True,
            expected_exit_code=0,
        )
        pkg_full = result.stdout.strip()
        log.info(f"Package in RPM DB: {pkg_full}")

        # Test 2b - version-release matches
        expected_vr = f"{meta.version}-{meta.release}"
        assert_that(pkg_full).described_as(
            "Installed package must contain expected VERSION-RELEASE"
        ).contains(expected_vr)
        log.info(f"Version-Release: {expected_vr}")

        # Test 3 - module file on disk
        result = node.execute(
            f"test -f {meta.module_file}", sudo=True
        )
        assert_that(result.exit_code).described_as(
            f"Module file {meta.module_file} must exist on disk"
        ).is_equal_to(0)
        log.info(f"Module file present: {meta.module_file}")

        # Test 4 - rpm -V
        result = node.execute(
            f"rpm -V {self.PKG_NAME}", sudo=True
        )
        assert_that(result.exit_code).described_as(
            "rpm -V must report no discrepancies"
        ).is_equal_to(0)
        log.info("rpm -V passed")

        # Test 5 - modules.dep
        result = node.execute(
            f"grep -q {meta.module_name} {dep_file}", sudo=True
        )
        assert_that(result.exit_code).described_as(
            f"Module '{meta.module_name}' must appear in {dep_file}"
        ).is_equal_to(0)
        log.info("Module found in modules.dep")

        # cleanup
        self._uninstall_rpm(node, log)

    # ── Phase 2: Module Loading (tests 6-13) ───────────────────────────

    @TestCaseMetadata(
        description="""
        Phase 2.1 - modinfo validation.
        6. modinfo reports information for the azihsm module.
        """,
        priority=2,
    )
    def verify_azihsm_modinfo(self, node: Node, log: Logger) -> None:
        rpm_path = self._get_rpm_path(node, log)
        meta = self._parse_rpm_metadata(node, log, rpm_path)
        self._skip_if_kernel_mismatch(node, log, meta.target_kernel)
        self._ensure_clean_state(node, log, meta.module_name)
        self._install_rpm(node, log, rpm_path)

        try:
            # Test 6 - modinfo succeeds
            modinfo = node.tools[Modinfo]
            info = modinfo.get_info(meta.module_name)
            assert_that(info).described_as(
                "modinfo must return information for the module"
            ).is_not_empty()
            log.info(f"modinfo output:\n{info}")
        finally:
            self._uninstall_rpm(node, log)

    @TestCaseMetadata(
        description="""
        Phase 2.2 - Full load / verify / unload cycle.
        7.  modprobe loads the module.
        8.  Module appears in lsmod.
        9.  No dmesg errors from the module.
        10. /proc/modules shows state = Live.
        11. modprobe -r unloads the module.
        12. Module gone from lsmod.
        """,
        priority=2,
    )
    def verify_azihsm_module_load_unload(
        self, node: Node, log: Logger
    ) -> None:
        rpm_path = self._get_rpm_path(node, log)
        meta = self._parse_rpm_metadata(node, log, rpm_path)
        self._skip_if_kernel_mismatch(node, log, meta.target_kernel)
        self._ensure_clean_state(node, log, meta.module_name)
        self._install_rpm(node, log, rpm_path)

        modprobe = node.tools[Modprobe]
        lsmod = node.tools[Lsmod]
        dmesg = node.tools[Dmesg]

        try:
            # Ensure unloaded before explicit load test
            if modprobe.is_module_loaded(
                meta.module_name, force_run=True, no_error_log=True
            ):
                modprobe.remove([meta.module_name])
                time.sleep(1)

            # Clear dmesg
            node.execute("dmesg -c", sudo=True)

            # Test 7 - modprobe loads module
            modprobe.load(meta.module_name)
            log.info("modprobe load succeeded")

            # Test 8 - module in lsmod
            assert_that(
                lsmod.module_exists(
                    mod_name=meta.module_name, force_run=True
                )
            ).described_as(
                f"'{meta.module_name}' must appear in lsmod"
            ).is_true()
            log.info("Module visible in lsmod")

            # Test 9 - no dmesg errors
            dmesg_output = dmesg.get_output(force_run=True)
            module_errors = [
                line
                for line in dmesg_output.splitlines()
                if meta.module_name in line.lower()
                and any(
                    kw in line.lower()
                    for kw in ("error", "fail", "bug", "oops", "panic")
                )
            ]
            assert_that(module_errors).described_as(
                f"No error/fail/bug/oops/panic messages for "
                f"{meta.module_name} in dmesg"
            ).is_empty()
            log.info(f"No dmesg errors related to {meta.module_name}")

            # Test 10 - /proc/modules state = Live
            result = node.execute(
                f"awk -v mod={meta.module_name} "
                "'$1 == mod {print $5}' /proc/modules",
                sudo=True,
            )
            assert_that(result.stdout.strip()).described_as(
                "Module state in /proc/modules must be 'Live'"
            ).is_equal_to("Live")
            log.info("Module state is Live")

            # Test 11 - modprobe -r succeeds
            modprobe.remove([meta.module_name])
            log.info("modprobe -r succeeded")

            # Test 12 - module gone from lsmod
            assert_that(
                lsmod.module_exists(
                    mod_name=meta.module_name, force_run=True
                )
            ).described_as(
                "Module must not appear in lsmod after removal"
            ).is_false()
            log.info("Module no longer in lsmod")

        finally:
            modprobe.remove([meta.module_name], ignore_error=True)
            self._uninstall_rpm(node, log)

    @TestCaseMetadata(
        description="""
        Phase 2.3 - Repeatable load/unload cycles.
        13. 3 consecutive modprobe / modprobe -r cycles succeed.
        """,
        priority=3,
    )
    def verify_azihsm_module_reload_cycles(
        self, node: Node, log: Logger
    ) -> None:
        rpm_path = self._get_rpm_path(node, log)
        meta = self._parse_rpm_metadata(node, log, rpm_path)
        self._skip_if_kernel_mismatch(node, log, meta.target_kernel)
        self._ensure_clean_state(node, log, meta.module_name)
        self._install_rpm(node, log, rpm_path)

        modprobe = node.tools[Modprobe]
        cycles = 3

        try:
            for i in range(1, cycles + 1):
                log.info(f"Load/unload cycle {i}/{cycles}")
                modprobe.load(meta.module_name)
                time.sleep(0.5)
                modprobe.remove([meta.module_name])
                time.sleep(0.5)

            log.info(f"{cycles} load/unload cycles completed successfully")

        finally:
            modprobe.remove([meta.module_name], ignore_error=True)
            self._uninstall_rpm(node, log)

    # ── Phase 3: Uninstallation (tests 14-18) ──────────────────────────

    @TestCaseMetadata(
        description="""
        Phase 3 - Uninstallation.
        14. rpm -evh removes without errors.
        15. Package no longer in RPM database.
        16. Module .ko file removed from disk.
        17. modprobe correctly fails after uninstall.
        18. No leftover files in module directory.
        """,
        priority=2,
    )
    def verify_azihsm_rpm_uninstallation(
        self, node: Node, log: Logger
    ) -> None:
        rpm_path = self._get_rpm_path(node, log)
        meta = self._parse_rpm_metadata(node, log, rpm_path)
        extra_dir = self._extra_dir(meta.target_kernel)

        # Start with the package installed
        self._ensure_clean_state(node, log, meta.module_name)
        self._install_rpm(node, log, rpm_path)

        # Make sure module is unloaded before removal
        modprobe = node.tools[Modprobe]
        if modprobe.is_module_loaded(
            meta.module_name, force_run=True, no_error_log=True
        ):
            modprobe.remove([meta.module_name], ignore_error=True)
            time.sleep(1)

        # Test 14 - RPM removal succeeds
        result = node.execute(
            f"rpm -evh {self.PKG_NAME}", sudo=True
        )
        assert_that(result.exit_code).described_as(
            "RPM removal must succeed"
        ).is_equal_to(0)
        log.info("RPM removal succeeded")

        # Test 15 - package gone from RPM database
        result = node.execute(
            f"rpm -q {self.PKG_NAME}", sudo=True, no_error_log=True
        )
        assert_that(result.exit_code).described_as(
            f"Package '{self.PKG_NAME}' must not be in RPM database"
        ).is_not_equal_to(0)
        log.info("Package no longer in RPM database")

        # Test 16 - .ko file removed
        result = node.execute(
            f"test -f {meta.module_file}", sudo=True, no_error_log=True
        )
        assert_that(result.exit_code).described_as(
            f"Module file {meta.module_file} must be removed"
        ).is_not_equal_to(0)
        log.info("Module file removed from disk")

        # Test 17 - modprobe fails (only if kernel matches)
        uname = node.tools[Uname]
        info = uname.get_linux_information()
        running = info.kernel_version_raw
        if running == meta.target_kernel:
            result = node.execute(
                f"modprobe {meta.module_name}",
                sudo=True,
                no_error_log=True,
            )
            assert_that(result.exit_code).described_as(
                "modprobe must fail after uninstall"
            ).is_not_equal_to(0)
            log.info("modprobe correctly fails after RPM removal")
        else:
            log.info(
                f"Skipping post-uninstall load test "
                f"(kernel mismatch: {running} != {meta.target_kernel})"
            )

        # Test 18 - no leftover files
        result = node.execute(
            f"find {extra_dir} -name '{meta.module_name}*' 2>/dev/null",
            sudo=True,
            shell=True,
            no_error_log=True,
        )
        assert_that(result.stdout.strip()).described_as(
            f"No leftover module files in {extra_dir}"
        ).is_empty()
        log.info("No leftover files after uninstall")
