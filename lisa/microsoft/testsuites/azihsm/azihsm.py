# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re
from threading import Lock
from typing import List, cast
from weakref import WeakKeyDictionary, WeakSet

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Cat, Uname
from lisa.operating_system import CBLMariner, Posix, Ubuntu
from lisa.tools import (
    Dmesg,
    Echo,
    Lsmod,
    Mkdir,
    Modinfo,
    Modprobe,
    OpenSSL,
    Rm,
    Usermod,
)
from lisa.util import LisaException, check_till_timeout

AZIHSM_DEV = "/dev/azihsm0"
AZIHSM_NAME = "azihsm"
AZIHSM_BIN_DIR = "/usr/bin/azihsm"
_TESTING_REPO_ADDED_NODES: WeakSet[Node] = WeakSet()
_USER_GROUPS_ADDED_NODES: WeakSet[Node] = WeakSet()
_PACKAGES_INSTALLED_NODES: WeakSet[Node] = WeakSet()
_AZIHSM_DRIVER_PACKAGE_NAMES: WeakKeyDictionary[Node, str] = WeakKeyDictionary()
_AZIHSM_KMOD_PATHS: WeakKeyDictionary[Node, str] = WeakKeyDictionary()
_AZIHSM_KERNEL_VERSIONS: WeakKeyDictionary[Node, str] = WeakKeyDictionary()
# Guards access/mutation of the module-level state above, since test cases
# for different nodes may run concurrently.
_STATE_LOCK = Lock()


@TestSuiteMetadata(
    area="azihsm",
    category="functional",
    description="""
    Test suite for the azihsm driver and package. These tests cover package
    installation and cleanup, functional behavior of the driver, and
    verification of user space components such as the SDK API and the OpenSSL
    engine that uses azihsm.

    These tests assume that the packages to be tested are available via testing
    or preview releases in packages.microsoft.com.  The needed URLs will be
    added to the system and the package installed via apt or tdnf.
    """,
    maturity="preview",
    requirement=simple_requirement(
        supported_os=[CBLMariner, Ubuntu],
    ),
)
class AziHsm(TestSuite):
    @staticmethod
    def _new_dmesg_lines(
        pre_lines: List[str], post_lines: List[str]
    ) -> List[str]:
        # Return the dmesg lines appended since the "pre" snapshot was
        # captured. A ring buffer only ever drops lines from its front and
        # appends lines at its end, so "post" must be some suffix of "pre"
        # (if older lines were evicted) followed by newly appended lines.
        # Find the largest k such that the last k lines of "pre" equal the
        # first k lines of "post" - i.e. the maximal suffix-of-pre /
        # prefix-of-post overlap - and treat everything in "post" after
        # that overlap as new. Searching for an anchor sequence anywhere in
        # "post" (an earlier approach) is unsound: if that same sequence
        # also occurred earlier in "pre" itself, a match could be found at
        # the wrong (too early) position, misclassifying old lines as new.
        # Anchoring the overlap specifically at the start of "post" avoids
        # that ambiguity and remains correct whether or not the buffer
        # wrapped. If no overlap exists at all (the whole "pre" snapshot
        # has been evicted), this returns the whole "post" snapshot,
        # erring on the side of catching errors rather than missing them.
        max_overlap = min(len(pre_lines), len(post_lines))
        for overlap in range(max_overlap, 0, -1):
            if pre_lines[-overlap:] == post_lines[:overlap]:
                return post_lines[overlap:]
        return post_lines

    def check_azihsm_device(self, node: Node) -> None:
        if not node.shell.exists(node.get_pure_path(AZIHSM_DEV)):
            raise SkippedException(
                f"{AZIHSM_DEV} was not found. Verify that an AZIHSM device is "
                "attached to the test VM."
            )

    #
    # Collect extra diagnostics when an azihsm binary test fails under LISA.
    # This helps identify environment differences (permissions, device
    # ownership, stray processes, kernel messages, etc.) between a run
    # driven by LISA and a manual run on the same VM.
    #
    def _log_azihsm_test_failure_diagnostics(
        self, node: Node, log: Logger, test_name: str
    ) -> None:
        log.info(f"Collecting additional diagnostics for {test_name} failure")

        diagnostic_commands = [
            ("id", False),
            ("groups", False),
            (f"ls -la {node.get_pure_path(AZIHSM_DEV)}", True),
            ("ps -ef | grep -i azihsm", True),
            ("lsmod | grep -i azihsm", True),
        ]
        for command, sudo in diagnostic_commands:
            result = node.execute(
                command,
                shell=True,
                sudo=sudo,
                expected_exit_code=None,
            )
            log.info(f"[{command}]:\n{result.stdout.strip()}")

        try:
            # 200 lines is comfortably larger than the dmesg output produced
            # by a single azihsm test run, so the full module/device log
            # trail leading up to the failure is captured without pulling in
            # an excessive amount of unrelated kernel log history.
            dmesg_output = node.tools[Dmesg].get_output(
                force_run=True, tail_lines=200
            )
            log.info(f"[dmesg tail]:\n{dmesg_output}")
        except LisaException as e:
            log.error(f"Failed to collect dmesg output: {e}")

    #
    # Make sure the azihsm package repository is configured for this system.
    #
    def setup_package_repository(self, node: Node, log: Logger) -> None:
        # Get the kernel version so we can build some names used later
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(force_run=True).kernel_version_raw

        if isinstance(node.os, Ubuntu):
            driver_package_name = f"azihsm-module-{kernel_version}"
            kmod_path = f"/lib/modules/{kernel_version}/updates/azihsm.ko"
        elif isinstance(node.os, CBLMariner):
            driver_package_name = f"azihsm-driver-{kernel_version}"
            kmod_path = f"/lib/modules/{kernel_version}/extra/azihsm.ko"
        else:
            raise SkippedException(
                f"AZIHSM is not supported on {node.os.name}. "
                "Supported operating systems are Ubuntu and CBLMariner."
            )

        with _STATE_LOCK:
            _AZIHSM_DRIVER_PACKAGE_NAMES[node] = driver_package_name
            _AZIHSM_KMOD_PATHS[node] = kmod_path
            _AZIHSM_KERNEL_VERSIONS[node] = kernel_version
            repo_already_added = node in _TESTING_REPO_ADDED_NODES

        log.info(f"Driver Package {driver_package_name}")
        log.info(f"Driver Path {kmod_path}")
        log.info(f"Kernel Version {kernel_version}")

        if repo_already_added:
            return

        # Mark the node dirty before mutating it so that a partial failure
        # here doesn't leave a modified environment eligible for reuse.
        node.mark_dirty()

        log.info("Adding PMC testing repository")
        if isinstance(node.os, Ubuntu):
            node.os.add_repository(
                repo=(
                    "deb https://packages.microsoft.com/ubuntu/"
                    f"{node.os.information.release}/prod testing main"
                ),
                repo_name="AZIHSM Packages",
                keys_location=[
                    "https://packages.microsoft.com/keys/microsoft.asc",
                    "https://packages.microsoft.com/keys/microsoft-rolling.asc",
                ],
            )
        else:
            # Azure Linux prior to 3.0 is not supported by AziHSM
            major_version = node.os.information.version.major
            if major_version < 3:
                raise SkippedException(
                    f"AZIHSM is not supported on Azure Linux "
                    f"{node.os.information.release}. Azure Linux 3.0 or "
                    "later is required."
                )
            arch_name = node.os.get_kernel_information().hardware_platform
            if major_version == 3:
                node.os.add_repository(
                    repo=(
                        "https://packages.microsoft.com/azurelinux/"
                        f"{node.os.information.release}/preview/"
                        f"ms-oss/{arch_name}/"
                    ),
                    repo_name="AZIHSM Packages",
                    keys_location=[
                        "https://packages.microsoft.com/keys/microsoft.asc",
                        "https://packages.microsoft.com/keys/microsoft-rolling.asc",
                    ],
                )
                node.os.add_repository(
                    repo=(
                        "https://packages.microsoft.com/azurelinux/"
                        f"{node.os.information.release}/preview/"
                        f"ms-non-oss/{arch_name}/"
                    ),
                    repo_name="AZIHSM Packages Non-OSS",
                    keys_location=[
                        "https://packages.microsoft.com/keys/microsoft.asc",
                        "https://packages.microsoft.com/keys/microsoft-rolling.asc",
                    ],
                )
            elif major_version == 4:
                node.os.add_repository(
                    repo=(
                        "https://packages.microsoft.com/azurelinux/"
                        "4/preview/"
                        f"microsoft/{arch_name}/"
                    ),
                    repo_name="AZIHSM Packages",
                    keys_location=[
                        "https://packages.microsoft.com/keys/microsoft.asc",
                        "https://packages.microsoft.com/keys/microsoft-rolling.asc",
                    ],
                )
            else:
                raise SkippedException(
                    "AZIHSM repository configuration is not defined for Azure "
                    f"Linux {node.os.information.release}. Add the matching "
                    "package repository before running this suite."
                )

        # Indicate we have done this step already
        with _STATE_LOCK:
            _TESTING_REPO_ADDED_NODES.add(node)

    #
    # Make sure the test user is a member of the groups needed to access the
    # azihsm device and the tss keys.
    #
    def setup_user_groups(self, node: Node, log: Logger) -> None:
        with _STATE_LOCK:
            groups_already_added = node in _USER_GROUPS_ADDED_NODES

        if groups_already_added:
            return

        usermod = node.tools[Usermod]
        for group in ["azihsm", "tss"]:
            log.info(f"Adding user to group {group}")
            usermod.add_user_to_group(group=group, sudo=True)

        # Group membership changes don't apply to the already-established
        # session. Close it so the next command reconnects with a fresh
        # login that picks up the new group membership.
        node.shell.close()
        node.shell.initialize()

        # Indicate we have done this step already
        with _STATE_LOCK:
            _USER_GROUPS_ADDED_NODES.add(node)

    #
    # Make sure all of the azihsm package are installed and up-to-date
    #
    def install_azihsm_driver_package(self, node: Node, log: Logger) -> None:
        # Make sure we've added the AZIHSM repo
        self.setup_package_repository(node=node, log=log)
        with _STATE_LOCK:
            driver_package_name = _AZIHSM_DRIVER_PACKAGE_NAMES[node]
        # Package management APIs are only available on Posix operating
        # systems, which is enforced by this suite's supported_os.
        posix_os = cast(Posix, node.os)

        log.info(f"Checking package {driver_package_name}")

        # Check that the package is already installed
        package_exists = posix_os.package_exists(driver_package_name)

        if not package_exists:
            # Check that the package is available in configured repositories
            if not posix_os.is_package_in_repo(driver_package_name):
                raise SkippedException(
                    f"{driver_package_name} package not found in repositories. "
                    "Check that a package that matches the target "
                    "kernel version exists."
                )

            # Package is available, install it
            log.info(f"Installing package {driver_package_name}")
            posix_os.install_packages(driver_package_name, signed=True)

            # Verify package is installed
            package_installed = posix_os.package_exists(driver_package_name)
            assert_that(package_installed).described_as(
                f"{driver_package_name} package should be installed"
            ).is_true()
        else:
            # Make sure everything is up-to-date
            log.info(f"Updating package {driver_package_name}")
            posix_os.update_packages(driver_package_name)
            # Verify package was installed
            package_installed = posix_os.package_exists(driver_package_name)
            log.info(f"{driver_package_name} status {package_installed}")
            assert_that(package_installed).described_as(
                f"{driver_package_name} package should be installed"
            ).is_true()

    #
    # Make sure all of the azihsm packages are installed and up-to-date
    #
    def install_all_azihsm_packages(self, node: Node, log: Logger) -> None:
        with _STATE_LOCK:
            if node in _PACKAGES_INSTALLED_NODES:
                return

        # Make sure we've added the AZIHSM repo
        self.setup_package_repository(node=node, log=log)

        if isinstance(node.os, Ubuntu):
            azihsm_pkg_list = [
                "azihsm-driver-tests",
                "azihsm-sdk-tests",
                "azihsm-tools",
                "libazihsm",
                "libazihsm-dev",
                "libengine-azihsm-openssl",
            ]
        elif isinstance(node.os, CBLMariner):
            azihsm_pkg_list = [
                "azihsm-driver-tests",
                "azihsm-sdk-tests",
                "azihsm-tools",
                "libazihsm",
                "libazihsm-devel",
                "libengine-azihsm-openssl",
            ]
        else:
            raise SkippedException(
                f"AZIHSM is not supported on {node.os.name}. "
                "Supported operating systems are Ubuntu and CBLMariner."
            )

        # Package management APIs are only available on Posix operating
        # systems, which is enforced by this suite's supported_os.
        posix_os = cast(Posix, node.os)

        for pkg in azihsm_pkg_list:
            log.info(f"Checking package {pkg}")

            # Check if the package is already installed
            package_exists = posix_os.package_exists(pkg)

            if not package_exists:
                # Check if package is available in repositories
                if not posix_os.is_package_in_repo(pkg):
                    raise SkippedException(
                        f"{pkg} package not found in repositories. "
                        "Check that a package that matches the distro "
                        "and architecture exists."
                    )

                # Package is available, install it
                log.info(f"Installing package {pkg}")
                posix_os.install_packages(pkg, signed=True)

                # Verify package is installed
                package_installed = posix_os.package_exists(pkg)
                assert_that(package_installed).described_as(
                    f"{pkg} package should be installed"
                ).is_true()
            else:
                # Make sure everything is up-to-date
                log.info(f"Updating package {pkg}")
                posix_os.update_packages(pkg)
                # Verify package was installed
                package_installed = posix_os.package_exists(pkg)
                assert_that(package_installed).described_as(
                    f"{pkg} package should be installed"
                ).is_true()

        # Make sure the test user can access the azihsm device and tss keys
        self.setup_user_groups(node=node, log=log)

        # Indicate we have done this step already
        with _STATE_LOCK:
            _PACKAGES_INSTALLED_NODES.add(node)

    #
    # Start of Test Cases
    #

    @TestCaseMetadata(
        description="""
        Package installation tests

        Phase 1 - Installation.
        1. Package installs without errors.
        2. Package registered in package database.
        3. Module .ko file exists on disk.
        4. rpm -V (CBLMariner) / dpkg -V (Ubuntu) reports no discrepancies.
        5. depmod registered the module in modules.dep.
            """,
        priority=1,
    )
    def verify_package_installation(self, node: Node, log: Logger) -> None:
        # Make sure we've added the AZIHSM repo
        self.setup_package_repository(node=node, log=log)
        node.mark_dirty()  # this case installs the driver package
        with _STATE_LOCK:
            driver_package_name = _AZIHSM_DRIVER_PACKAGE_NAMES[node]
            kernel_version = _AZIHSM_KERNEL_VERSIONS[node]
            kmod_path = _AZIHSM_KMOD_PATHS[node]
        # Package management APIs are only available on Posix operating
        # systems, which is enforced by this suite's supported_os.
        posix_os = cast(Posix, node.os)

        #
        # Remove the driver package so that we can explicitly test its install
        package_installed = posix_os.package_exists(driver_package_name)
        if package_installed:
            log.info(f"Uninstalling {driver_package_name}")
            posix_os.uninstall_packages(driver_package_name)

        #
        # Test 1 - Package installs without errors
        log.info(f"Installing {driver_package_name}")
        posix_os.install_packages(driver_package_name, signed=True)

        #
        # Test 2 - Package is registered in the package database
        log.info(f"Checking {driver_package_name}")
        package_installed = posix_os.package_exists(driver_package_name)
        assert_that(package_installed).described_as(
            f"{driver_package_name} package should be installed"
        ).is_true()

        #
        # Test 3 - Module .ko file exists on disk
        log.info(f"Checking for {kmod_path}")
        assert_that(node.shell.exists(node.get_pure_path(kmod_path))).described_as(
            f"{kmod_path} should exist after package installation"
        ).is_true()

        #
        # Test 4 - rpm -V / dpkg -V reports no discrepancies
        if isinstance(node.os, CBLMariner):
            verify_cmd = f"rpm -V {driver_package_name}"
        else:
            # Ubuntu/Debian
            verify_cmd = f"dpkg -V {driver_package_name}"
        verify_result = node.execute(
            verify_cmd,
            sudo=True,
            shell=True,
            expected_exit_code=None,
        )
        # dpkg -V (and rpm -V) report discrepancies as lines on stdout
        # without necessarily setting a non-zero exit code, so the exit
        # code alone is not sufficient evidence of a clean result; stdout
        # must also be empty.
        verify_stdout = verify_result.stdout.strip()
        assert_that(
            verify_result.exit_code == 0 and not verify_stdout
        ).described_as(
            f"{verify_cmd} reported discrepancies for {driver_package_name}: "
            f"exit code {verify_result.exit_code}, stdout: {verify_stdout}"
        ).is_true()
        log.info(f"{driver_package_name} passed integrity verification")

        #
        # Test 5 - depmod registered the module in modules.dep
        remcat = node.tools[Cat]
        contents = remcat.read(
            f"/lib/modules/{kernel_version}/modules.dep", force_run=True
        )

        # kmod_path is an absolute path such as
        # /lib/modules/<kernel_version>/extra/azihsm.ko or
        # .../updates/azihsm.ko. Match the path relative to the kernel's
        # modules directory, rather than a bare "azihsm.ko" substring, so a
        # stale/duplicate module elsewhere in the tree cannot cause a false
        # positive.
        modules_dir_prefix = f"/lib/modules/{kernel_version}/"
        assert_that(kmod_path).described_as(
            f"kmod_path {kmod_path} should be under {modules_dir_prefix}"
        ).starts_with(modules_dir_prefix)
        relative_kmod_path = kmod_path[len(modules_dir_prefix) :]
        assert_that(contents).described_as(
            "modules.dep does not contain the AZIHSM kernel module at "
            f"{relative_kmod_path}"
        ).contains(relative_kmod_path)

    #
    #
    @TestCaseMetadata(
        description="""
        Phase 2.1 - modinfo validation.
        6. modinfo reports information for the azihsm module.
            """,
        priority=1,
    )
    def verify_azihsm_modinfo(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)
        self.check_azihsm_device(node=node)
        with _STATE_LOCK:
            driver_package_name = _AZIHSM_DRIVER_PACKAGE_NAMES[node]

        #
        # Test 6 - modinfo succeeds
        try:
            modinfo = node.tools[Modinfo]
            info = modinfo.get_info(AZIHSM_NAME)
            assert_that(info).described_as(
                "modinfo must return information for the module"
            ).is_not_empty()
            log.info(f"modinfo output:\n{info}")
        finally:
            # Uninstalling the driver package leaves the environment modified.
            node.mark_dirty()
            cast(Posix, node.os).uninstall_packages(driver_package_name)

    #
    #
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
        priority=1,
    )
    def verify_azihsm_module_load_unload(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)
        self.check_azihsm_device(node=node)
        node.mark_dirty()  # this case loads/unloads kernel modules
        with _STATE_LOCK:
            driver_package_name = _AZIHSM_DRIVER_PACKAGE_NAMES[node]

        # Tools we need
        modprobe = node.tools[Modprobe]
        lsmod = node.tools[Lsmod]

        try:
            # ensure the module is unloaded before the test
            if modprobe.is_module_loaded(
                AZIHSM_NAME, force_run=True, no_error_log=True
            ):
                modprobe.remove([AZIHSM_NAME])
                check_till_timeout(
                    lambda: not modprobe.is_module_loaded(
                        AZIHSM_NAME, force_run=True, no_error_log=True
                    ),
                    timeout_message="Wait for module to unload",
                )
            log.info("module is not loaded as desired")

            # Capture a dmesg baseline before loading, so Test 9 below only
            # inspects lines newly appended by this load - not stale
            # messages left over from earlier test cases (e.g. driver/SDK
            # resiliency tests that deliberately exercise abort paths).
            pre_load_dmesg_lines = node.tools[Dmesg].get_output(
                force_run=True
            ).splitlines()

            #
            # Test 7 -  modprobe loads module
            modprobe.load(AZIHSM_NAME)
            log.info("modprobe load succeeded")

            #
            # Test 8 -  module in lsmod
            assert_that(lsmod.module_exists(AZIHSM_NAME, force_run=True)).described_as(
                f"{AZIHSM_NAME} must appear in lsmod"
            ).is_true()
            log.info("Modules visible in lsmod")

            #
            # Test 9 -  No dmesg errors from the module
            post_load_dmesg_lines = node.tools[Dmesg].get_output(
                force_run=True
            ).splitlines()
            new_dmesg_lines = self._new_dmesg_lines(
                pre_load_dmesg_lines, post_load_dmesg_lines
            )
            azihsm_lines = [
                line for line in new_dmesg_lines if AZIHSM_NAME in line.lower()
            ]
            error_lines = [
                line
                for line in azihsm_lines
                if re.search(
                    r"\b(error|fail(ed|ure)?|panic|oops|bug)\b", line, re.IGNORECASE
                )
            ]
            assert_that(error_lines).described_as(
                "dmesg should not report azihsm error signatures after "
                f"loading the module: {error_lines}"
            ).is_empty()
            log.info("No azihsm error signatures found in dmesg after module load")

            #
            # Test 10 -  /proc/modules shows state - Live
            result = node.execute(
                f"awk -v mod={AZIHSM_NAME} "
                "'$1 == mod {print $5}' "
                f"{node.get_pure_path('/proc/modules')}",
                sudo=True,
                shell=True,
            )

            assert_that(result.stdout.strip()).described_as(
                "Module state in /proc/modules must be 'Live'"
            ).is_equal_to("Live")
            log.info("Module state is Live")

            #
            # Test 11 -  modprobe -r succeeds
            modprobe.remove([AZIHSM_NAME])
            log.info("modprobe -r succeeded")

            #
            # Test 12 - module gone from lsmod
            assert_that(
                lsmod.module_exists(mod_name=AZIHSM_NAME, force_run=True)
            ).described_as("Module must not appear in lsmod after removal").is_false()

        finally:
            # Clean up
            modprobe.remove([AZIHSM_NAME], ignore_error=True)
            cast(Posix, node.os).uninstall_packages(driver_package_name)

    #
    #
    @TestCaseMetadata(
        description="""
        Phase 2.3 - Repeatable load/unload cycles.
        13. 3 consecutive modprobe / modprobe -r cycles succeed.
            """,
        priority=1,
    )
    def verify_azihsm_module_reload_cycles(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)
        self.check_azihsm_device(node=node)
        node.mark_dirty()  # this case loads/unloads kernel modules
        with _STATE_LOCK:
            driver_package_name = _AZIHSM_DRIVER_PACKAGE_NAMES[node]

        # Tools we need
        modprobe = node.tools[Modprobe]
        cycles = 3  # Just cycle through a few times

        try:
            # Ensure the module starts unloaded so every cycle below performs
            # a real load, rather than the first cycle's load being a no-op
            # if the module was already loaded (e.g. by check_azihsm_device).
            if modprobe.is_module_loaded(
                AZIHSM_NAME, force_run=True, no_error_log=True
            ):
                modprobe.remove([AZIHSM_NAME])
                check_till_timeout(
                    lambda: not modprobe.is_module_loaded(
                        AZIHSM_NAME, force_run=True, no_error_log=True
                    ),
                    timeout_message="Wait for module to unload",
                )

            #
            # Test 13 - 3 consecutive modprobe / modprobe -r cycles succeed
            for i in range(1, cycles + 1):
                log.info(f"Load/unload cycle {i}/{cycles}")
                # Load the module
                modprobe.load(AZIHSM_NAME)
                check_till_timeout(
                    lambda: modprobe.is_module_loaded(
                        AZIHSM_NAME, force_run=True, no_error_log=True
                    ),
                    timeout_message="Wait for module to load",
                )
                log.info("module loaded")

                # Unload the module
                modprobe.remove([AZIHSM_NAME])
                check_till_timeout(
                    lambda: not modprobe.is_module_loaded(
                        AZIHSM_NAME, force_run=True, no_error_log=True
                    ),
                    timeout_message="Wait for module to unload",
                )
                log.info("module unloaded")

            log.info(f"{cycles} load/unload cycles completed successfully")

        finally:
            # Clean up
            modprobe.remove([AZIHSM_NAME], ignore_error=True)
            cast(Posix, node.os).uninstall_packages(driver_package_name)

    @TestCaseMetadata(
        description="""
        Phase 3 - Uninstallation.
        14. Package removes without errors.
        15. Package no longer in package database.
        16. Module .ko file removed from disk.
        17. modprobe correctly fails after uninstall.
        18. No leftover files in module directory.
            """,
        priority=1,
    )
    def verify_azihsm_package_uninstallation(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)
        self.check_azihsm_device(node=node)
        node.mark_dirty()  # this case uninstalls the driver package
        with _STATE_LOCK:
            driver_package_name = _AZIHSM_DRIVER_PACKAGE_NAMES[node]
            kmod_path = _AZIHSM_KMOD_PATHS[node]
        # Package management APIs are only available on Posix operating
        # systems, which is enforced by this suite's supported_os.
        posix_os = cast(Posix, node.os)

        # Capture the package's owned files (regular files only) before
        # uninstalling, via the package manifest, so Test 18 below can
        # verify specifically that *this* package's files are gone -
        # rather than assuming the module directory is empty, which would
        # false-fail if other drivers share it.
        if isinstance(node.os, CBLMariner):
            manifest_cmd = f"rpm -ql {driver_package_name}"
        else:
            # Ubuntu/Debian
            manifest_cmd = f"dpkg -L {driver_package_name}"
        manifest_result = node.execute(manifest_cmd, sudo=True, shell=True)
        owned_files = [
            path
            for path in (
                line.strip() for line in manifest_result.stdout.splitlines()
            )
            if path.startswith("/")
            and not node.shell.is_dir(node.get_pure_path(path))
        ]

        #
        # Test 14 - Package removal succeeds
        # The package unloads the module
        posix_os.uninstall_packages(driver_package_name)
        log.info("Package successfully removed")

        #
        # Test 15 - package gone from package database
        package_installed = posix_os.package_exists(driver_package_name)
        assert_that(package_installed).described_as(
            f"{driver_package_name} package should NOT be installed"
        ).is_false()
        log.info("Package no longer in package database")

        #
        # Test 16 - .ko file removed
        assert_that(node.shell.exists(node.get_pure_path(kmod_path))).described_as(
            "The driver module is still present after the package was removed"
        ).is_false()
        log.info("Module file removed from disk")

        #
        # Test 17 - modprobe fails
        module_exists = node.tools[Modprobe].module_exists(AZIHSM_NAME)
        assert_that(module_exists).described_as(
            "modprobe should fail after the package is uninstalled"
        ).is_false()
        log.info("modprobe correctly failed")

        #
        # Test 18 - no leftover files
        # Check specifically for this package's own files (captured from
        # the package manifest before uninstall), rather than assuming the
        # whole module directory is empty - other drivers may share it.
        leftover_files = [
            path for path in owned_files if node.shell.exists(node.get_pure_path(path))
        ]
        assert_that(leftover_files).described_as(
            f"Files owned by {driver_package_name} should not remain after "
            f"uninstall: {leftover_files}"
        ).is_empty()
        log.info("No leftover AZIHSM files found after uninstall")

    #
    #
    @TestCaseMetadata(
        description="""
            Run the driver tests
            """,
        priority=1,
    )
    def verify_azihsm_driver_tests(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)
        self.check_azihsm_device(node=node)
        node.mark_dirty()  # this case installs packages and runs driver tests

        # Make sure the azihsm packages are installed
        self.install_all_azihsm_packages(node=node, log=log)

        # The driver tests exercise a single, exclusively-owned azihsm device,
        # so running them multi-threaded causes contention/failures. Force
        # single-threaded execution, matching the SDK tests below.
        params = "--test-threads 1"

        result = node.execute(
            f"{node.get_pure_path(AZIHSM_BIN_DIR) / 'driver_tests'} {params}",
            # driver_tests runs against real, TPM-backed hardware. Without
            # AZIHSM_USE_TPM=1 the test helpers take the mock BK3 path
            # (treating sealed_bk3 as masked_bk3), which is invalid on real
            # hardware and results in UnmaskingBk3Failed. Match the SDK
            # tests below, which already set this.
            update_envs={"AZIHSM_USE_TPM": "1"},
            timeout=1800,  # Allow up to 30 minutes for the driver tests.
            # Don't assert here so we can log full output/diagnostics below
            # before failing, whether the failure is a bad exit code or
            # simply missing "PASSED" in the output.
            expected_exit_code=None,
            no_info_log=False,
        )
        log.info(f"driver_tests exit code: {result.exit_code}")
        if result.stderr.strip():
            log.info(f"driver_tests stderr:\n{result.stderr.strip()}")

        if result.exit_code != 0:
            self._log_azihsm_test_failure_diagnostics(
                node=node, log=log, test_name="driver_tests"
            )

        # driver_tests is a Rust test binary (like the SDK tests below).
        # cargo test's pretty-printed output can include a literal terminfo
        # padding artifact (e.g. "ok\x0f$<2>.") when run over a
        # non-interactive SSH session, which breaks a literal substring
        # match on "test result: ok.". The process exit code (0 on success,
        # 101 if any test fails) is the authoritative signal, so rely on
        # that instead, matching azihsm_api_cpp_tests below.
        assert_that(result.exit_code).described_as(
            "AZIHSM driver tests failed. Review the command output "
            "above and any AZIHSM/kernel logs to diagnose the cause."
        ).is_equal_to(0)

    #
    #
    @TestCaseMetadata(
        description="""
            Run the sdk tests
            """,
        priority=1,
        # This case runs 5 SDK binaries sequentially, each with its own
        # 1800s (30 minute) execute() timeout, so the aggregate worst case
        # is up to 9000s. Set the case timeout above that aggregate so LISA
        # doesn't abort the case before later SDK tests finish.
        timeout=9600,
    )
    def verify_azihsm_sdk_tests(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)
        self.check_azihsm_device(node=node)
        node.mark_dirty()  # this case installs packages and runs sdk tests

        # Make sure the azihsm packages are installed
        self.install_all_azihsm_packages(node=node, log=log)

        sdk_test_list = [
            "azihsm_api",
            # "azihsm_api_cpp_tests", - do this separately
            "azihsm_api_native",
            "azihsm_api_tests",
            "azihsm_ddi_tests",
        ]

        # The rust based tests only work single threaded
        params = "--test-threads 1"
        failed_tests = []

        for test in sdk_test_list:
            log.info(f"Running {test}")
            try:
                result = node.execute(
                    f"{node.get_pure_path(AZIHSM_BIN_DIR) / test} {params}",
                    update_envs={"AZIHSM_USE_TPM": "1"},
                    timeout=1800,
                    # Don't assert here; the exit code is checked manually
                    # below so we can log full output/diagnostics first.
                    expected_exit_code=None,
                    no_info_log=False,
                )
            except LisaException as e:
                log.error(
                    f"{test} raised an exception: {e}. See the azihsm "
                    "diagnostics logged immediately below for details."
                )
                failed_tests.append(f"{test} ({e})")
                self._log_azihsm_test_failure_diagnostics(
                    node=node, log=log, test_name=test
                )
                continue

            log.info(f"{test} exit code: {result.exit_code}")
            if result.stderr.strip():
                log.info(f"{test} stderr:\n{result.stderr.strip()}")

            # These are Rust test binaries. The process exit code (0 on
            # success, non-zero if any test fails) is the authoritative
            # signal: cargo test's pretty-printed output can include a
            # literal terminfo padding artifact (e.g. "ok\x0f$<2>.") when
            # run over a non-interactive SSH session, which breaks a
            # literal substring match on "test result: ok.".
            if result.exit_code == 0:
                log.info(f"{test} Passed")
            else:
                log.info(f"{test} Failed")
                failed_tests.append(test)
                self._log_azihsm_test_failure_diagnostics(
                    node=node, log=log, test_name=test
                )

        # Do the api_cpp_tests here because its output format differs from the
        # Rust-based tests above; use the process exit code to determine
        # success instead of matching a Rust-specific "test result: ok." line.
        test = "azihsm_api_cpp_tests"
        log.info(f"Running {test}")
        try:
            result = node.execute(
                f"{node.get_pure_path(AZIHSM_BIN_DIR) / test}",
                update_envs={"AZIHSM_USE_TPM": "1",
                             "AZIHSM_DISABLE_MULTI_PROCESS_TESTS": "1"},
                timeout=1800,
                expected_exit_code=None,
                no_info_log=False,
            )
        except LisaException as e:
            log.error(
                f"{test} raised an exception: {e}. See the azihsm "
                "diagnostics logged immediately below for details."
            )
            failed_tests.append(f"{test} ({e})")
            self._log_azihsm_test_failure_diagnostics(
                node=node, log=log, test_name=test
            )
        else:
            log.info(f"{test} exit code: {result.exit_code}")
            if result.stderr.strip():
                log.info(f"{test} stderr:\n{result.stderr.strip()}")

            if result.exit_code == 0:
                log.info(f"{test} Passed")
            else:
                log.info(f"{test} Failed")
                failed_tests.append(test)
                self._log_azihsm_test_failure_diagnostics(
                    node=node, log=log, test_name=test
                )

        assert_that(failed_tests).described_as(
            "Not all SDK tests passed, failed tests: "
            f"{failed_tests}. Review the command output above for each "
            "failing test to diagnose the cause."
        ).is_empty()

    #
    #
    @TestCaseMetadata(
        description="""
            Verify the azihsm OpenSSL provider (packaged as
            libengine-azihsm-openssl) is installed and loads via
            openssl.cnf.

            Note: this case deliberately stops short of exercising key
            generation (openssl genpkey/storeutl against the azihsm
            provider). The device's BK3 base key is one-shot per physical
            power cycle, and once *any* consumer (this test, the driver
            tests, or the SDK tests) initializes it, later init attempts
            from a different caller only succeed with a cached MOBK file
            from that original init. In practice this state has been
            observed to persist even across an Azure VM deallocate/start
            cycle (it lives on the physical HSM card, not the VM/OS disk),
            so a key-generation assertion here would be flaky across
            repeated CI runs rather than a reliable functional check.
            """,
        priority=1,
    )
    def verify_azihsm_openssl_engine(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)
        self.check_azihsm_device(node=node)
        node.mark_dirty()  # this case installs packages and runs the engine

        # Make sure the azihsm packages (including the OpenSSL provider) are
        # installed
        self.install_all_azihsm_packages(node=node, log=log)

        openssl = node.tools[OpenSSL]

        # The modules directory differs across distros (e.g. /usr/lib64/
        # ossl-modules on CBLMariner vs. /usr/lib/<arch>/ossl-modules on
        # Ubuntu), so ask OpenSSL where it is instead of hard-coding a path.
        version_result = openssl.run(
            "version -m",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to query the OpenSSL modules directory"
            ),
        )
        modules_dir_match = re.search(
            r'MODULESDIR:\s*"([^"]+)"', version_result.stdout
        )
        assert_that(modules_dir_match).described_as(
            "Unexpected `openssl version -m` output: "
            f"{version_result.stdout}"
        ).is_not_none()
        modules_dir_match = cast(re.Match[str], modules_dir_match)
        provider_so = f"{modules_dir_match.group(1)}/azihsm_provider.so"
        assert_that(
            node.shell.exists(node.get_pure_path(provider_so))
        ).described_as(
            f"azihsm OpenSSL provider module not found at {provider_so}"
        ).is_true()

        # Use an isolated scratch directory for the provider config so
        # repeated runs don't collide with each other or leave stale state
        # behind. No OBK/POTA/credentials are provisioned here: see the
        # docstring above for why key generation isn't exercised yet.
        work_dir = node.get_pure_path("/tmp/azihsm_openssl_engine_test")
        node.tools[Rm].remove_directory(str(work_dir), sudo=True)
        node.tools[Mkdir].create_directory(str(work_dir), sudo=True)

        try:
            openssl_cnf_path = work_dir / "openssl.cnf"
            bmk_path = work_dir / "bmk.bin"
            muk_path = work_dir / "muk.bin"
            openssl_cnf_contents = (
                "openssl_conf = openssl_init\n"
                "[openssl_init]\n"
                "providers = provider_sect\n"
                "[provider_sect]\n"
                "default = default_sect\n"
                "azihsm = azihsm_sect\n"
                "[default_sect]\n"
                "activate = 1\n"
                "[azihsm_sect]\n"
                f"module = {provider_so}\n"
                "activate = 1\n"
                f"azihsm-bmk-path = {bmk_path}\n"
                f"azihsm-muk-path = {muk_path}\n"
                "azihsm-api-revision = 1.0\n"
            )
            node.tools[Echo].write_to_file(
                openssl_cnf_contents,
                openssl_cnf_path,
                sudo=True,
                ignore_error=False,
            )

            # Confirm the provider actually loads and is reported as
            # available via the generated openssl.cnf.
            list_result = openssl.run(
                "list -providers",
                sudo=True,
                force_run=True,
                update_envs={"OPENSSL_CONF": str(openssl_cnf_path)},
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Failed to list OpenSSL providers"
                ),
            )
            assert_that(list_result.stdout).described_as(
                "azihsm provider was not loaded by OpenSSL: "
                f"{list_result.stdout}"
            ).contains("azihsm")
        finally:
            node.tools[Rm].remove_directory(str(work_dir), sudo=True)
