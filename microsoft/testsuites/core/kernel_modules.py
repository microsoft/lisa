# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Dict, List

from assertpy import assert_that
from semver import VersionInfo

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD, Redhat
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.tools import KernelConfig, LisDriver, Lsinitrd, Lsmod, Modinfo, Modprobe
from lisa.util import LisaException, SkippedException


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite covers test cases previously handled by LISAv2:
    LIS-MODULES-CHECK, VERIFY-LIS-MODULES-VERSION,
    INITRD-MODULES-CHECK, RELOAD-MODULES-SMP

    It is responsible for ensuring the Hyper V drivers are all present,
    are included in initrd, and are all the same version.
    """,
    requirement=simple_requirement(supported_platform_type=[AZURE, HYPERV, READY]),
)
class HvModule(TestSuite):
    _not_built_in_modules: List[str] = []
    _not_built_in_hv_modules: List[str] = []
    _built_in_modules: List[str] = []
    _built_in_hv_modules: List[str] = []

    @TestCaseMetadata(
        description="""
        This test case will
        1. Verify the list of given LIS kernel modules and verify if the version
           matches with the Linux kernel release number. (Drivers loaded directly in
           to the kernel are skipped)
        """,
        priority=2,
    )
    def verify_lis_modules_version(self, node: Node) -> None:
        if not isinstance(node.os, Redhat):
            raise SkippedException(
                f"{node.os.name} not supported. "
                "This test case only supports Redhat distros."
            )

        lis_installed = node.os.package_exists("microsoft-hyper-v")

        if not lis_installed:
            raise SkippedException("This test case requires LIS to be installed")

        modinfo = node.tools[Modinfo]
        lis_driver = node.tools[LisDriver]
        lis_version = lis_driver.get_version()

        hv_modules = self._get_not_built_in_modules(node)
        for module in hv_modules:
            module_version = VersionInfo.parse(modinfo.get_version(module))
            assert_that(module_version).described_as(
                f"Version of {module} does not match LIS version"
            ).is_equal_to(lis_version)

    @TestCaseMetadata(
        description="""
        This test case will ensure all necessary hv_modules are present in
        initrd. This is achieved by
        1. Skipping any modules that are loaded directly in the kernel
        2. Use lsinitrd tool to check whether a necessary module is missing
        """,
        priority=1,
        requirement=simple_requirement(
            unsupported_os=[BSD],
        ),
    )
    def verify_initrd_modules(self, environment: Environment) -> None:
        node = environment.nodes[0]
        # 1) Takes all of the necessary modules and removes
        #    those that are statically loaded into the kernel
        all_necessary_hv_modules_file_names = {
            "hv_storvsc": "hv_storvsc.ko",
            "hv_netvsc": "hv_netvsc.ko",
            "hv_vmbus": "hv_vmbus.ko",
            "hid_hyperv": "hid-hyperv.ko",
            "hyperv_keyboard": "hyperv-keyboard.ko",
            "wdt": "wdt.ko",
        }
        skip_modules = self._get_built_in_modules(node)
        hv_modules_file_names = {
            k: v
            for (k, v) in all_necessary_hv_modules_file_names.items()
            if k not in skip_modules
        }

        # 2) Use lsinitrd to check whether a necessary module
        #    is missing.
        lsinitrd = node.tools[Lsinitrd]
        missing_modules = []
        try:
            for module in hv_modules_file_names:
                if not lsinitrd.has_module(
                    module_file_name=hv_modules_file_names[module]
                ):
                    missing_modules.append(module)
        except (LisaException, AssertionError) as e:
            # Skip CVM images and other images with initrdless boot
            raise SkippedException(e)

        if (
            isinstance(environment.platform, AzurePlatform)
            and "hid_hyperv" in missing_modules
        ):
            missing_modules.remove("hid_hyperv")

        assert_that(missing_modules).described_as(
            "Required Hyper-V modules are missing from initrd."
        ).is_length(0)

    @TestCaseMetadata(
        description="""
        This test case will
        1. Verify the presence of all Hyper V drivers using lsmod
           to look for the drivers not directly loaded into the kernel.
        """,
        priority=1,
    )
    def verify_hyperv_modules(self, log: Logger, environment: Environment) -> None:
        node = environment.nodes[0]
        if not self._not_built_in_hv_modules:
            self._get_not_built_in_modules(node)

        hv_modules = self._not_built_in_hv_modules
        distro_version = node.os.information.version
        if len(hv_modules) == 0:
            raise SkippedException(
                "Hyper-V drivers are statically built into the kernel"
            )

        # Some versions of RHEL and CentOS have the LIS package installed
        #   which includes extra drivers
        if isinstance(node.os, Redhat):
            modprobe = node.tools[Modprobe]
            lis_installed = node.os.package_exists("microsoft-hyper-v")

            if lis_installed:
                hv_modules.append("pci_hyperv")
                modprobe.run("pci_hyperv", sudo=True)

            if (
                distro_version >= "7.3.0" or distro_version < "7.5.0"
            ) and lis_installed:
                hv_modules.append("mlx4_en")
                modprobe.run("mlx4_en", sudo=True)

        # Counts the Hyper V drivers loaded as modules
        missing_modules = []
        lsmod = node.tools[Lsmod]
        for module in hv_modules:
            if lsmod.module_exists(module):
                log.info(f"Module {module} present")
            else:
                log.error(f"Module {module} absent")
                missing_modules.append(module)

        if (
            isinstance(environment.platform, AzurePlatform)
            and "hid_hyperv" in missing_modules
        ):
            missing_modules.remove("hid_hyperv")
        assert_that(missing_modules).described_as(
            "Not all Hyper V drivers are present."
        ).is_length(0)

    @TestCaseMetadata(
        description="""
        This test case will
        1. Verify the presence of all essential non Hyper V kernel drivers using lsmod
           to look for the drivers not directly loaded into the kernel.
        """,
        priority=1,
    )
    def verify_kernel_modules(self, log: Logger, environment: Environment) -> None:
        node = environment.nodes[0]

        # Counts the Hyper V drivers loaded as modules
        missing_modules = []
        lsmod = node.tools[Lsmod]
        for module in hv_modules:
            if lsmod.module_exists(module):
                log.info(f"Module {module} present")
            else:
                log.error(f"Module {module} absent")
                missing_modules.append(module)

        if (
            isinstance(environment.platform, AzurePlatform)
            and "hid_hyperv" in missing_modules
        ):
            missing_modules.remove("hid_hyperv")
        assert_that(missing_modules).described_as(
            "Not all Hyper V drivers are present."
        ).is_length(0)

    @TestCaseMetadata(
        description="""
        This test case will reload hyper-v modules for 100 times.
        """,
        priority=1,
        requirement=simple_requirement(
            min_core_count=4,
        ),
    )
    def verify_reload_hyperv_modules(self, log: Logger, node: Node) -> None:
        # Constants
        module = "hv_netvsc"
        loop_count = 100

        if isinstance(node.os, Redhat):
            try:
                log.debug("Checking LIS installation before reload.")
                node.tools.get(LisDriver)
            except Exception:
                log.debug("Updating LIS failed. Moving on to attempt reload.")

        if not self._not_built_in_hv_modules:
            self._get_not_built_in_modules(node)
        if module not in self._not_built_in_hv_modules:
            raise SkippedException(
                f"{module} is loaded statically into the "
                "kernel and therefore can not be reloaded"
            )

        result = node.execute(
            ("for i in $(seq 1 %i); do " % loop_count)
            + f"modprobe -r -v {module}; modprobe -v {module}; "
            "done; sleep 1; "
            "ip link set eth0 down; ip link set eth0 up; dhclient eth0",
            sudo=True,
            shell=True,
        )

        if "is in use" in result.stdout:
            raise SkippedException(
                f"Module {module} is in use so it cannot be reloaded"
            )

        assert_that(result.stdout.count("rmmod")).described_as(
            f"Expected {module} to be removed {loop_count} times"
        ).is_equal_to(loop_count)
        assert_that(result.stdout.count("insmod")).described_as(
            f"Expected {module} to be inserted {loop_count} times"
        ).is_equal_to(loop_count)

    def _get_kernel_modules_configuration(self, node: Node) -> Dict[str, str]:
        """
        Returns a dictionary of kernel modules and their configuration names.
        This is used to determine which modules are built into the kernel
        and which are not. The configuration names are used to check if the
        modules are built-in or not.
        """
        return {
            "wdt": "CONFIG_WATCHDOG",
            "cifs": "CONFIG_CIFS",
        }

    def _get_hv_kernel_modules_configuration(self, node: Node) -> Dict[str, str]:
        """
        Returns a dictionary of hv kernel modules and their configuration names.
        This is used to determine which modules are built into the kernel
        and which are not. The configuration names are used to check if the
        modules are built-in or not.
        """
        if isinstance(node.os, BSD):
            return {
                "hv_storvsc": "vmbus/storvsc",
                "hv_netvsc": "vmbus/hn",
                "hyperv_keyboard": "vmbus/hv_kbd",
            }
        else:
            return {
                "hv_storvsc": "CONFIG_HYPERV_STORAGE",
                "hv_netvsc": "CONFIG_HYPERV_NET",
                "hv_vmbus": "CONFIG_HYPERV",
                "hv_utils": "CONFIG_HYPERV_UTILS",
                "hid_hyperv": "CONFIG_HID_HYPERV_MOUSE",
                "hv_balloon": "CONFIG_HYPERV_BALLOON",
                "hyperv_keyboard": "CONFIG_HYPERV_KEYBOARD",
            }

    def _get_built_in_modules(self, node: Node) -> None:
        """
        Returns the hv_modules that are directly loaded into the kernel and
        therefore would not show up in lsmod or be needed in initrd.
        """
        if self._built_in_hv_modules and self._built_in_modules:
            return
        hv_modules_configuration = self._get_hv_kernel_modules_configuration(node)

        for module in hv_modules_configuration:
            if node.tools[KernelConfig].is_built_in(
                hv_modules_configuration[module]
            ):
                self._built_in_hv_modules.append(module)
        kernel_modules_configuration = self._get_kernel_modules_configuration(node)
        for module in kernel_modules_configuration:
            if node.tools[KernelConfig].is_built_in(
                kernel_modules_configuration[module]
            ):
                self._built_in_modules.append(module)

    def _get_not_built_in_modules(self, node: Node) -> None:
        """
        Returns the kernel modules that are not directly loaded into the kernel and
        therefore would be expected to show up in lsmod.
        """
        if self._not_built_in_hv_modules and self._not_built_in_modules:
            return
        kernel_modules_configuration = self._get_hv_kernel_modules_configuration(node)
        for module in kernel_modules_configuration:
            if not node.tools[KernelConfig].is_built_in(
                kernel_modules_configuration[module]
            ):
                self._not_built_in_hv_modules.append(module)
        kernel_modules_configuration = self._get_kernel_modules_configuration(node)
        for module in kernel_modules_configuration:
            if not node.tools[KernelConfig].is_built_in(
                kernel_modules_configuration[module]
            ):
                self._not_built_in_modules.append(module)
