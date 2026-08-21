# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import time

from assertpy import assert_that, contents_of

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Uname
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.tools import Lsmod, Modinfo, Modprobe

AZIHSM_DEV = "/dev/azihsm0"
AZIHSM_NAME = "azihsm"

testing_repo_added = False
packages_installed = False


@TestSuiteMetadata(
    area="azihsm",
    category="functional",
    description="""
    Test suite for the azihsm driver and package. These tests cover package
    installation and cleanup, functional behavior of the driver, and
    verification of user space components such as the SDK API and the OpenSSL
    engine that uses azihsm.

    These tests assume that the packages to be tested is available via testing
    or preview releases in packages.microsoft.com.  The needed URLs will be
    added to the system and the package installed via apt or tdnf.
    """,
    owner="Microsoft",
    requirement=simple_requirement(
        supported_os=[CBLMariner, Ubuntu],
    ),
)
class AziHsm(TestSuite):
    AziHsmDrvPkgName = ""
    kmodpath = ""
    kernel_version = ""

    #
    # Make sure the azihsm package repository is configured for this system.
    #
    def setup_package_repository(self, node: Node, log: Logger) -> None:
        global testing_repo_added
        if testing_repo_added is True:
            return

        log.info("Adding PMC testing repository")
        if isinstance(node.os, Ubuntu):
            node.os.add_repository(
                repo=(
                    "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] "
                    "https://packages.microsoft.com/ubuntu/"
                    f"{node.os.information.release}/prod testing main"
                ),
                repo_file="microsoft-testing.list",
                repo_name="AZIHSM Packages",
            )
        if isinstance(node.os, CBLMariner):
            arch_name = node.os.get_kernel_information().hardware_platform
            node.os.add_repository(
                repo=(
                    "http://packages.microsoft.com/azurelinux/"
                    f"{node.os.information.release}/preview/"
                    f"ms-oss/{arch_name}/"
                ),
                repo_file="preview-ms-oss.repo",
                repo_name="AZIHSM Packages",
            )

        # Get the kernel version so we can build some names used later
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(force_run=True).kernel_version_raw

        # Store the kernel driver package name in an instance
        # variable so we can access it throughout the tests
        if isinstance(node.os, Ubuntu):
            AziHsm.AziHsmDrvPkgName = f"azihsm-module-{kernel_version}"
            AziHsm.kmodpath = f"/lib/modules/{kernel_version}/updates/azihsm.ko"
        if isinstance(node.os, CBLMariner):
            AziHsm.AziHsmDrvPkgName = f"azihsm-driver-{kernel_version}"
            AziHsm.kmodpath = f"/lib/modules/{kernel_version}/extra/azihsm.ko"
        AziHsm.kernel_version = kernel_version
        log.info(f"Driver Package {AziHsm.AziHsmDrvPkgName}")
        log.info(f"Driver Path {AziHsm.kmodpath}")
        log.info(f"Kernel Version {AziHsm.kernel_version}")

        # Indicate we have done this step already
        testing_repo_added = True

    #
    # Make sure all of the azihsm package are installed and up-to-date
    #
    def install_azihsm_driver_package(self, node: Node, log: Logger) -> None:
        # Make sure we've added the AZIHSM repo
        self.setup_package_repository(node=node, log=log)

        log.info(f"Checking package {AziHsm.AziHsmDrvPkgName}")

        # Check if the package is already installed
        package_exists = node.os.package_exists(AziHsm.AziHsmDrvPkgName)

        if not package_exists:
            # Check is package is avaialble is repositories
            if not node.os.is_package_in_repo(AziHsm.AziHsmDrvPkgName):
                raise SkippedException(
                    f"{AziHsm.AziHsmDrvPkgName} package not found in repositories"
                )

            # Package is available, install it
            log.info(f"Installing package {AziHsm.AziHsmDrvPkgName}")
            node.os.install_packages(AziHsm.AziHsmDrvPkgName)

            # Verify package is installed
            package_installed = node.os.package_exists(AziHsm.AziHsmDrvPkgName)
            assert_that(package_installed).described_as(
                f"{AziHsm.AziHsmDrvPkgName} package should be installed"
            ).is_true()
        else:
            # Make sure everything is up-to-date
            log.info(f"Updating package {AziHsm.AziHsmDrvPkgName}")
            node.os.update_packages(AziHsm.AziHsmDrvPkgName)
            # Verify package was installed
            package_installed = node.os.package_exists(AziHsm.AziHsmDrvPkgName)
            log.info(f"{AziHsm.AziHsmDrvPkgName} status {package_installed}")
            assert_that(package_installed).described_as(
                f"{AziHsm.AziHsmDrvPkgName} package should be installed"
            ).is_true()

    #
    # Make sure all of the azihsm package are installed and up-to-date
    #
    def install_all_azihsm_packages(self, node: Node, log: Logger) -> None:
        global packages_installed
        if packages_installed is True:
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
        if isinstance(node.os, CBLMariner):
            azihsm_pkg_list = [
                "azihsm-driver-tests",
                "azihsm-sdk-tests",
                "azihsm-tools",
                "libazihsm",
                "libazihsm-devel",
                "libengine-azihsm-openssl",
            ]

        for pkg in azihsm_pkg_list:
            log.info(f"Checking package {pkg}")

            # Check if the package is already installed
            package_exists = node.os.package_exists(pkg)

            if not package_exists:
                # Check is package is avaialble is repositories
                if not node.os.is_package_in_repo(pkg):
                    raise SkippedException(f"{pkg} package not found in repositories")

                # Package is available, install it
                log.info(f"Installing package {pkg}")
                node.os.install_packages(pkg)

                # Verify package is installed
                package_installed = node.os.package_exists(pkg)
                assert_that(package_installed).described_as(
                    f"{pkg} package should be installed"
                ).is_true()
            else:
                # Make sure everything is up-to-date
                log.info(f"Updating package {pkg}")
                node.os.update_packages(pkg)
                # Verify package was installed
                package_installed = node.os.package_exists(pkg)
                assert_that(package_installed).described_as(
                    f"{pkg} package should be installed"
                ).is_true()

        # Indicate we have done this step already
        packages_installed = True

    def check_driver_package_contents(self, node: Node, log: Logger) -> None:
        # Make sure the azihsm packages are installed
        self.install_all_azihsm_packages(node=node, log=log)

        log.info(f"Checking the driver for kernel version {AziHsm.kernel_version}")
        # Check that the driver exists where we expect it to be
        assert_that(AziHsm.kmodpath).is_file()

    #
    #
    # Start of Test Cases
    #
    #

    #
    #
    @TestCaseMetadata(
        description="""
        Package installation tests

        Phase 1 - Installation.
        1. Package installs without errors.
        2a. Package registered in RPM database.
        2b. Package version matches expected version.
        3. Module .ko file exists on disk.
        4. rpm -V reports no discrepancies.
        5. depmod registered the module in modules.dep.
            """,
        priority=0,
        requirement=simple_requirement(unsupported_os=[]),
    )
    def package_installation_tests(self, node: Node, log: Logger) -> None:
        # Make sure we've added the AZIHSM repo
        self.setup_package_repository(node=node, log=log)

        #
        # Remove the driver package so we can explicitely test its install
        log.info(f"Uninstalling {AziHsm.AziHsmDrvPkgName}")
        node.os.uninstall_packages(AziHsm.AziHsmDrvPkgName)

        #
        # Test 1 - Package installs without errors
        log.info(f"Installing {AziHsm.AziHsmDrvPkgName}")
        node.os.install_packages(AziHsm.AziHsmDrvPkgName)

        #
        # Test 2 - Package is registered in the package database
        log.info(f"Checking {AziHsm.AziHsmDrvPkgName}")
        package_installed = node.os.package_exists(AziHsm.AziHsmDrvPkgName)
        assert_that(package_installed).described_as(
            f"{AziHsm.AziHsmDrvPkgName} package should be installed"
        ).is_true()

        #
        # Test 3 - Module .ko file exists od disk
        log.info(f"Checking for {AziHsm.kmodpath}")
        node.shell.exists(node.get_pure_path(AziHsm.kmodpath))

        #
        # Test 4 - rpm -V reports no discrepancies
        # Skipping this until support is added to lisa/operating_system.py

        #
        # Test 5 - depmod registered the module in modules.dep
        contents = contents_of(
            f"/lib/modules/{AziHsm.kernel_version}/modules.dep", "ascii"
        )
        # Note: thiscould be under either 'extra' or 'updates'
        # We do not provide the subdir, so this driver located anywhere
        # in the tree would match and cause a false postive
        assert_that(contents).contains("azihsm.ko")

    #
    #
    @TestCaseMetadata(
        description="""
        Phase 2.1 - modinfo validation.
        6. modinfo reports information for the azihsm module.
            """,
        priority=0,
        requirement=simple_requirement(unsupported_os=[]),
    )
    def verify_azihsm_modinfo(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)

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
            node.os.uninstall_packages(AziHsm.AziHsmDrvPkgName)

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
        priority=0,
        requirement=simple_requirement(unsupported_os=[]),
    )
    def verify_azihsm_module_load_unload(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)

        # Tools we need
        modprobe = node.tools[Modprobe]
        lsmod = node.tools[Lsmod]

        try:
            try:
                # ensure the module is unloaded before the test
                if modprobe.is_module_loaded(
                    AZIHSM_NAME, force_run=True, no_error_log=True
                ):
                    modprobe.remove([AZIHSM_NAME])
                    for attempt in range(5):
                        if not modprobe.is_module_loaded(
                            AZIHSM_NAME, force_run=True, no_error_log=True
                        ):
                            break
                        else:
                            time.sleep(1)
            finally:
                log.info("module is not loaded as desired")

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
            # Test 9 -  No dmesg errors from themodule
            # Skipping this as normal loading does produce dmesg output

            #
            # Test 10 -  /proc/modules shows state - Live
            result = node.execute(
                f"awk -v mod={AZIHSM_NAME} " "'$1 == mod {print $5}' /proc/modules",
                sudo=True,
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
            node.os.uninstall_packages(AziHsm.AziHsmDrvPkgName)

    #
    #
    @TestCaseMetadata(
        description="""
        Phase 2.3 - Repeatable load/unload cycles.
        13. 3 consecutive modprobe / modprobe -r cycles succeed.
            """,
        priority=0,
        requirement=simple_requirement(unsupported_os=[]),
    )
    def verify_azihsm_module_reload_cycles(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)

        # Tools we need
        modprobe = node.tools[Modprobe]
        cycles = 3

        try:
            #
            # Test 13 - 3 consecutive modprobe / modprobe -r cycles succeed
            for i in range(1, cycles + 1):
                log.info(f"Load/unload cycle {i}/{cycles}")
                modprobe.load(AZIHSM_NAME)
                for attempt in range(5):
                    if modprobe.is_module_loaded(
                        AZIHSM_NAME, force_run=True, no_error_log=True
                    ):
                        break
                    else:
                        time.sleep(0.5)

                modprobe.remove([AZIHSM_NAME])
                for attempt in range(5):
                    if not modprobe.is_module_loaded(
                        AZIHSM_NAME, force_run=True, no_error_log=True
                    ):
                        break
                    else:
                        time.sleep(0.5)

            log.info(f"{cycles} load/unload cycles completed successfully")

        finally:
            # Clean up
            modprobe.remove([AZIHSM_NAME], ignore_error=True)
            node.os.uninstall_packages(AziHsm.AziHsmDrvPkgName)

    @TestCaseMetadata(
        description="""
        Phase 3 - Uninstallation.
        14. Package removes without errors.
        15. Package no longer in package database.
        16. Module .ko file removed from disk.
        17. modprobe correctly fails after uninstall.
        18. No leftover files in module directory.
            """,
        priority=0,
        requirement=simple_requirement(unsupported_os=[]),
    )
    def verify_azihsm_package_uninstallation(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)

        # Make sure module is unloaded before removal
        modprobe = node.tools[Modprobe]
        if modprobe.is_module_loaded(AZIHSM_NAME, force_run=True, no_error_log=True):
            modprobe.remove([AZIHSM_NAME], ignore_error=True)
            time.sleep(1)

        #
        # Test 14 - Package removal succeeds
        try:
            node.os.uninstall_packages(AziHsm.AziHsmDrvPkgName)
        except Exception as e:
            log.error(f"Uninstall failed {e}")
        finally:
            log.info("Package successfully removed")

        #
        # Test 15 - package gone from package database
        package_installed = node.os.package_exists(AziHsm.AziHsmDrvPkgName)
        assert_that(package_installed).described_as(
            f"{AziHsm.AziHsmDrvPkgName} package should NOT be installed"
        ).is_false()
        log.info("Package no longer in package database")

        #
        # Test 16 - .ko file removed
        assert_that(AziHsm.kmodpath).does_not_exist()
        log.info("Module file removed from disk")

        #
        # Test 17 - modprobe fails
        try:
            modprobe.load(AZIHSM_NAME)
        except Exception:
            log.info("modprobe correctly failed")

        #
        # Test 18 - no leftover files
        # Skipping this as it is possible for other drivers to also
        # be installed thus the updates directory will not always be empty

    #
    #
    @TestCaseMetadata(
        description="""
            Run the driver tests
            """,
        priority=0,
        requirement=simple_requirement(unsupported_os=[]),
    )
    def run_azihsm_driver_tests(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)

        # Make sure the azihsm packages are installed
        self.install_all_azihsm_packages(node=node, log=log)

        params = "--test-threads 1"

        try:
            result = node.execute(
                f"/usr/bin/azihsm/driver_tests {params}",
            )
        except Exception:
            log.info("test failed")
        finally:
            cmd_output = result.stdout.strip()
            assert_that("PASSED" in cmd_output, "Test did not contain PASSED").is_true()

    #
    #
    @TestCaseMetadata(
        description="""
            Run the sdk tests
            """,
        priority=0,
        requirement=simple_requirement(unsupported_os=[]),
    )
    def run_azihsm_sdk_tests(self, node: Node, log: Logger) -> None:
        # Make sure the driver package is installed
        self.install_azihsm_driver_package(node=node, log=log)

        # Make sure the azihsm packages are installed
        self.install_all_azihsm_packages(node=node, log=log)

        sdk_test_list = [
            "azihsm_api",
            # "azihsm_api_cpp_tests", - do this seperately
            "azihsm_api_native",
            "azihsm_api_tests",
            "azihsm_ddi_tests",
        ]

        params = "--test-threads 1"
        all_tests_passed = True

        for test in sdk_test_list:
            log.info(f"Running {test}")
            try:
                result = node.execute(
                    f"/usr/bin/azihsm/{test} {params}",
                    update_envs={"AZIHSM_USE_TPM": "1"},
                )
                cmd_output = result.stdout.strip()
            except Exception as e:
                cmd_output = ""
                log.info("Failed:", e)
                all_tests_passed = False

            if "test result: ok." in cmd_output:
                log.info(f"{test} Passed")
            else:
                log.info(f"{test} Failed")
                all_tests_passed = False

        # Do the api_cpp_tests here because the output is a different format
        log.info(f"Running {test}")
        test = "azihsm_api_cpp_tests"
        try:
            result = node.execute(
                f"/usr/bin/azihsm/{test} {params}",
                update_envs={"AZIHSM_USE_TPM": "1"},
                # sudo=True,
                # expected_exit_code=0,
            )
            cmd_output = result.stdout.strip()
        except Exception as e:
            cmd_output = ""
            log.info("Failed:", e)
            all_tests_passed = False

        if "test result: ok." in cmd_output:
            log.info(f"{test} Passed")
        else:
            log.info(f"{test} Failed")
            all_tests_passed = False

        assert_that(all_tests_passed, "Not all SDK tests passed").is_true()
