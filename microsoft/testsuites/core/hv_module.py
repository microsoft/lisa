# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List

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
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.sut_orchestrator.azure.tools import LisDriver
from lisa.tools import Find, KernelConfig, Lsinitrd, Lsmod, Modinfo, Modprobe, Uname
from lisa.util import SkippedException


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
    requirement=simple_requirement(supported_platform_type=["azure", "ready"]),
)
class HvModule(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will
        1. Verify the list of given LIS kernel modules and verify if the version
           matches with the Linux kernel release number. (Drivers loaded directly in
           to the kernel are skipped)
        """,
        priority=1,
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
        2. Find the path of initrd file
        3. Use lsinitrd tool to check whether a necessary module is missing
        """,
        priority=2,
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
        }
        skip_modules = self._get_built_in_modules(node)
        hv_modules_file_names = {
            k: v
            for (k, v) in all_necessary_hv_modules_file_names.items()
            if k not in skip_modules
        }

        # 2) Find the path of initrd
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information().kernel_version_raw
        find = node.tools[Find]
        initrd_possible_file_names = [
            f"initrd-{kernel_version}",
            f"initramfs-{kernel_version}.img",
            f"initrd.img-{kernel_version}",
        ]

        initrd_file_path = ""
        for file_name in initrd_possible_file_names:
            cmd_result = find.find_files(
                node.get_pure_path("/boot"), file_name, sudo=True
            )
            if cmd_result and cmd_result[0]:
                initrd_file_path = cmd_result[0]
                break

        # 3) Use lsinitrd to check whether a necessary module
        #    is missing.
        lsinitrd = node.tools[Lsinitrd]
        missing_modules = []
        for module in hv_modules_file_names:
            if not lsinitrd.has_module(
                module_file_name=hv_modules_file_names[module],
                initrd_file_path=initrd_file_path,
            ):
                missing_modules.append(module)

        if (
            isinstance(environment.platform, AzurePlatform)
            and "hid_hyperv" in missing_modules
        ):
            missing_modules.remove("hid_hyperv")

        assert_that(missing_modules).described_as(
            "Required Hyper-V modules are missing from initrd."
        ).is_length(0)

    def _get_built_in_modules(self, node: Node) -> List[str]:
        """
        Returns the hv_modules that are directly loaded into the kernel and
        therefore would not show up in lsmod or be needed in initrd.
        """
        hv_modules_configuration = {
            "hv_storvsc": "CONFIG_HYPERV_STORAGE",
            "hv_netvsc": "CONFIG_HYPERV_NET",
            "hv_vmbus": "CONFIG_HYPERV",
            "hv_utils": "CONFIG_HYPERV_UTILS",
            "hid_hyperv": "CONFIG_HID_HYPERV_MOUSE",
            "hv_balloon": "CONFIG_HYPERV_BALLOON",
            "hyperv_keyboard": "CONFIG_HYPERV_KEYBOARD",
        }

        modules = []
        for module in hv_modules_configuration:
            if node.tools[KernelConfig].is_built_in(hv_modules_configuration[module]):
                modules.append(module)

        return modules

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
        hv_modules = self._get_not_built_in_modules(node)
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

        if module not in self._get_not_built_in_modules(node):
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

    def _get_not_built_in_modules(self, node: Node) -> List[str]:
        """
        Returns the hv_modules that are not directly loaded into the kernel and
        therefore would be expected to show up in lsmod.
        """
        if isinstance(node.os, BSD):
            hv_modules_configuration = {
                "hv_storvsc": "vmbus/storvsc",
                "hv_netvsc": "vmbus/hn",
                "hyperv_keyboard": "vmbus/hv_kbd",
            }
        else:
            hv_modules_configuration = {
                "hv_storvsc": "CONFIG_HYPERV_STORAGE",
                "hv_netvsc": "CONFIG_HYPERV_NET",
                "hv_vmbus": "CONFIG_HYPERV",
                "hv_utils": "CONFIG_HYPERV_UTILS",
                "hid_hyperv": "CONFIG_HID_HYPERV_MOUSE",
                "hv_balloon": "CONFIG_HYPERV_BALLOON",
                "hyperv_keyboard": "CONFIG_HYPERV_KEYBOARD",
            }
        modules = []
        for module in hv_modules_configuration:
            if not node.tools[KernelConfig].is_built_in(
                hv_modules_configuration[module]
            ):
                modules.append(module)

        return modules
