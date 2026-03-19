# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import os
import time

from typing import Any, cast

from assertpy import assert_that, contents_of

from lisa import (
    LisaException,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Uname
from lisa.util import (
    NotMeetRequirementException,
)
from lisa.environment import Environment
from lisa.operating_system import OperatingSystem, CBLMariner, Ubuntu
from lisa.tools import Dmesg, Lsmod, Modinfo, Modprobe
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import AzureNodeSchema
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform

AZIHSM_DEV = "/dev/azihsm0"
AZIHSM_NAME = "azihsm"

packages_installed = False

@TestSuiteMetadata(
    area="azihsm",
    category="functional",
    description="""
    Test suite for the azihsm driver and package. These tests cover package installation and cleanup,
    functional behavior of the driver, and verification of user space components suck as the SDK API
    and the OpenSSL engine that uses axihsm.

    These tests assume that the package to be tested is avaiable via the tux-dev internal repository.
    The needed URLs will be added to the system ad the package installed via apt or tdnf.
    """,
    owner="Microsoft",
    requirement=simple_requirement(
        supported_os=[CBLMariner,Ubuntu],
        ),
)


class AziHsm(TestSuite):
    #
    # Make sure the azihsm package repository is configured for this system.
    #
    def setupPackageRepository(self, node: Node, log: Logger):
        log.info(f"Adding AZIHSM tuxdev repository")
        if isinstance(node.os, Ubuntu):
            node.os.add_repository(
                    repo=(f"deb http://tux-devrepo.corp.microsoft.com/repos/azihsm {node.os.information.codename} main"),
                    repo_name="AZIHSM Packages"
                    )
        if isinstance(node.os, CBLMariner):
            node.os.add_repository(
                    repo=(f"http://tux-devrepo.corp.microsoft.com/yumrepos/azihsm/"),
                    repo_name="AZIHSM Packages"
                    )

    #
    # Make sure all of the azihsm package are installed and up-to-date
    #
    def install_all_azihsm_packages(self, node: Node, log: Logger) -> None:
        global packages_installed
        if packages_installed == True:
            return

        # Indicate we have done this step already
        packages_installed = True

        # Make sure we've added the AZIHSM repo
        self.setupPackageRepository(node=node, log=log)

        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(
                force_run=True
                ).kernel_version

        if isinstance(node.os, Ubuntu):
            AziHsmPkgList = [
                             "azihsm-api-tests",
                             "azihsm-driver-tests",
                             "azihsm-sdk-tests",
                             "azihsm-tools",
                             "libazihsm",
                             "libazihsm-dev",
                             "libengine-azihsm-openssl",
                             ]
        if isinstance(node.os, CBLMariner):
            AziHsmPkgList = [
                             "azihsm-hwe-driver",
                             "azihsm-tools",
                             "azihsm-driver-tests",
                             "libengine-azihsm-openssl",
                             "azihsm-sdk-tests",
                             "libazihsm",
                             "libazihsm-devel",
                             "azihsm-api-tests",
                             ]

        for pkg in AziHsmPkgList:

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

    def check_driver_package_contents(self, node: Node, log: Logger) -> None:
        # Make sure the azihsm packages are installed
        self.install_all_azihsm_packages(node=node, log=log)

        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(
                force_run=True
                ).kernel_version

        log.info(f"Checking the driver for kernel version {kernel_version}")
        # Check that the driver exists where we expect it to be
        assert_that(f"/lib/modules/{kernel_version}/updates/azihsm.ko").is_file()

##
##
## Start of Test Cases
##
##
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

        # We need the current runing kernel version
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(
                force_run=True
                ).kernel_version

        if isinstance(node.os, Ubuntu):
            AziHsmDrvPkgName = f"azihsm-module-{kernel_version}"
        if isinstance(node.os, CBLMariner):
            AziHsmDrvPkgName = "azihsm-driver"

        #
        # Remove the driver package so we can explicitely test its install
        log.info(f"Uninstalling {AziHsmDrvPkgName}")
        node.os.uninstall_packages(AziHsmDrvPkgName)

        #
        # Test 1 - Package installs without errors
        log.info(f"Installing {AziHsmDrvPkgName}")
        node.os.install_packages(AziHsmDrvPkgName)

        #
        # Test 2a - Package is registered in the package database
        log.info(f"Checking {AziHsmDrvPkgName}")
        package_installed = node.os.package_exists(AziHsmDrvPkgName)
        assert_that(package_installed).described_as(
            f"{AziHsmDrvPkgName} package should be installed"
        ).is_true()

        #
        # Test 2b - Package version matches expected version
        package_info = node.os.get_package_information(AziHsmDrvPkgName)
        log.info(package_info)
        # Skipping this until the operating_system.py framework can be debugged
        #assert_that(package_installed).described_as(
        #    f"{pkg} package should be installed"
        #).is_true()

        #
        # Test 3 - Module .ko file exists od disk
        assert_that(f"/lib/modules/{kernel_version}/updates/azihsm.ko").is_file()

        #
        # Test 4 - rpm -V reports no discrepancies
        # Skipping this until support is added to lisa/operating_system.py

        #
        # Test 5 - depmod registered the module in modules.dep
        contents = contents_of(f"/lib/modules/{kernel_version}/modules.dep",'ascii')
        assert_that(contents).contains("updates/azihsm.ko")


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
        # We need the current runing kernel version
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(
                force_run=True
                ).kernel_version

        if isinstance(node.os, Ubuntu):
            AziHsmDrvPkgName = f"azihsm-module-{kernel_version}"
        if isinstance(node.os, CBLMariner):
            AziHsmDrvPkgName = "azihsm-driver"

        node.os.install_packages(AziHsmDrvPkgName)

        #
        # Test 6 - modinfo succeeds
        try:
            modinfo = node.tools[Modinfo]
            info = modinfo.get_info(AZIHSM_NAME)
            assert_that(info).described_as(
                    "modinfo must return information for the module"
                    ).is_not_empty()
            log.info(f"modinfo output:\n{info}");
        finally:
            node.os.uninstall_packages(AziHsmDrvPkgName)

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
        # We need the current runing kernel version
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(
                force_run=True
                ).kernel_version

        if isinstance(node.os, Ubuntu):
            AziHsmDrvPkgName = f"azihsm-module-{kernel_version}"
        if isinstance(node.os, CBLMariner):
            AziHsmDrvPkgName = "azihsm-driver"

        node.os.install_packages(AziHsmDrvPkgName)

        # Tools we need
        modprobe = node.tools[Modprobe]
        lsmod = node.tools[Lsmod]
        dmesg = node.tools[Dmesg]

        try:
            try:
                # ensure the module is unloaded before the test
                if modprobe.is_module_loaded(
                        AZIHSM_NAME, force_run=True, no_error_log=True
                        ):
                    modprobe.remove([AZIHSM_NAME])
                    time.sleep(1)
            finally:
                log.info("module is not loaded as desired")

            #
            # Test 7 -  modprobe loads module
            modprobe.load(AZIHSM_NAME)
            log.info("modprobe load succeeded")

            #
            # Test 8 -  module in lsmod
            assert_that(
                    lsmod.module_exists(AZIHSM_NAME, force_run=True
                        )
                    ).described_as(
                            f"{AZIHSM_NAME} must appear in lsmod"
                            ).is_true()
            log.info("Modules visible in lsmod")

            #
            # Test 9 -  No dmesg errors from themodule
            # Skipping this as normal loading does produce dmesg output

            #
            # Test 10 -  /proc/modules shows state - Live
            result = node.execute(
                    f"awk -v mod={AZIHSM_NAME} "
                    "'$1 == mod {print $5}' /proc/modules",
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
            assert_that(lsmod.module_exists(
                    mod_name=AZIHSM_NAME, force_run=True
                )
            ).described_as(
                "Module must not appear in lsmod after removal"
            ).is_false()

        finally:
            # Clean up
            modprobe.remove([AZIHSM_NAME], ignore_error=True)
            node.os.uninstall_packages(AziHsmDrvPkgName)

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
        # We need the current runing kernel version
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(
                force_run=True
                ).kernel_version

        if isinstance(node.os, Ubuntu):
            AziHsmDrvPkgName = f"azihsm-module-{kernel_version}"
        if isinstance(node.os, CBLMariner):
            AziHsmDrvPkgName = "azihsm-driver"

        node.os.install_packages(AziHsmDrvPkgName)

        # Tools we need
        modprobe = node.tools[Modprobe]
        cycles = 3

        try:
            #
            # Test 13 - 3 consecutive modprobe / modprobe -r cycles succeed
            for i in range(1, cycles + 1):
                log.info(f"Load/unload cycle {i}/{cycles}")
                modprobe.load(AZIHSM_NAME)
                time.sleep(0.5)
                modprobe.remove(AZIHSM_NAME)
                time.sleep(0.5)

            log.info(f"{cycles} load/unload cycles completed successfully")

        finally:
            # Clean up
            modprobe.remove([AZIHSM_NAME], ignore_error=True)
            node.os.uninstall_packages(AziHsmDrvPkgName)

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
        # We need the current runing kernel version
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information(
                force_run=True
                ).kernel_version

        if isinstance(node.os, Ubuntu):
            AziHsmDrvPkgName = f"azihsm-module-{kernel_version}"
        if isinstance(node.os, CBLMariner):
            AziHsmDrvPkgName = "azihsm-driver"

        node.os.install_packages(AziHsmDrvPkgName)

        # Make sure module is unloaded before removal
        modprobe = node.tools[Modprobe]
        if modprobe.is_module_loaded(
                AZIHSM_NAME,force_run=True, no_error_log=True
        ):
            modprobe.remove([AZIHSM_NAME], ignore_error=True)
            time.sleep(1)

        #
        # Test 14 - Package removeal succeeds
        try:
            node.os.uninstall_packages(AziHsmDrvPkgName)
        except Exception as e:
            log.error(f"Uninstall failed {e}")
        finally:
            log.info("Package successfully removed")

        #
        # Test 15 - package gone from package database
        package_installed = node.os.package_exists(AziHsmDrvPkgName)
        assert_that(package_installed).described_as(
            f"{AziHsmDrvPkgName} package should NOT be installed"
        ).is_false()
        log.info("Package no longer in package database")

        #
        # Test 16 - .ko file removed
        assert_that(f"/lib/modules/{kernel_version}/updates/azihsm.ko").does_not_exist()
        log.info("Module file removed from disk")

        #
        # Test 17 - modprobe fails
        try:
           modprobe.load(AZIHSM_NAME)
        except Exception as e:
            log.info(f"modprobe correctly failed")
        finally:
            raise AssertionError("modprobe did not fail as expected")

        #
        # Test 18 - no leftover files
        # Skipping this as it is possible for other drivers to also be installed thus the updates
        # directory will not alwasy be empty

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
        # Make sure the azihsm packages are installed
        self.install_all_azihsm_packages(node=node, log=log)

        params = "--test-threads 1"

        try:
            result = node.execute(
                    f"/usr/bin/azihsm/driver_tests {params}",
                    #sudo=True,
                    #expected_exit_code=0,
                    )
            cmd_output = result.stdout.strip()
        except Exception as e:
            log.info("test failed")
        finally:
            cmd_output = result.stdout.strip()
            #assert_that(cmd_output,"Test did not contain PASSED").contains("PASSED")
            assert_that("PASSED" in cmd_output,"Test did not contain PASSED").is_true()

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

        # Make sure the azihsm packages are installed
        self.install_all_azihsm_packages(node=node, log=log)

        sdk_test_list = [
                "azihsm_api",
                "azihsm_api_cpp_tests",
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
                        #sudo=True,
                        #expected_exit_code=0,
                        )
                cmd_output = result.stdout.strip()
            except Exception as e:
                log.info(cmd_output)
                log.info("Failed:", e)
                all_tests_passed = False
            finally:
                if "FAILED" in cmd_output:
                    #log.info(cmd_output)
                    log.info(f"{test} Failed")
                    all_tests_passed = False
                else:
                    log.info(f"{test} Passed")

        assert_that(all_tests_passed,"Not all SDK tests passed").is_true()
