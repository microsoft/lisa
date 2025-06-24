# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Cat
from lisa.features.security_profile import CvmDisabled
from lisa.operating_system import BSD, Fedora, Posix, Suse, Ubuntu, Windows
from lisa.sut_orchestrator import AZURE, READY
from lisa.tools import Dmesg, Echo, KernelConfig, Lsmod, Reboot, Sed
from lisa.util import SkippedException, get_matched_str
from microsoft.testsuites.display.modetest import Modetest

GRUB_CMDLINE_LINUX_DEFAULT_PATTERN = re.compile(
    r'GRUB_CMDLINE_LINUX_DEFAULT="(?P<grub_cmdline>.*)"', re.M
)


@TestSuiteMetadata(
    area="drm",
    category="functional",
    description="""
    This test suite uses to verify drm driver sanity.
    """,
    requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
)
class Drm(TestSuite):
    @TestCaseMetadata(
        description="""
        This case is to check whether the hyperv_drm driver registered successfully.
        Once driver is registered successfully it should appear in `lsmod` output.

        Steps,
        1. lsmod
        2. Check if hyperv_drm exist in the list.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_drm_driver(self, node: Node, log: Logger) -> None:
        if not isinstance(node.os, Posix):
            raise SkippedException(
                f"{node.os.name} {node.os.information.version} is not supported."
            )
        kernel_info = (
            f"{node.os.information.full_version} {node.os.get_kernel_information()}"
        )
        is_built_in = node.tools[KernelConfig].is_built_in("CONFIG_DRM_HYPERV")
        has_hyperv_drm = node.tools[Lsmod].module_exists("hyperv_drm")
        has_hyperv_fb = node.tools[Lsmod].module_exists("hyperv_fb")

        # Get marketplace information from Azure node runbook
        marketplace_info = "Unknown"
        try:
            from lisa.sut_orchestrator.azure.common import AzureNodeSchema

            azure_runbook = node.capability.get_extended_runbook(
                AzureNodeSchema, "azure"
            )
            if azure_runbook and azure_runbook.marketplace:
                marketplace_info = azure_runbook.get_image_name()
        except Exception:
            # If not Azure or unable to get marketplace info, use "Unknown"
            pass

        log.debug(
            f"OS DRM Summary: {kernel_info} | "
            f"OS Full Version: {node.os.information.full_version} | "
            f"Marketplace: {marketplace_info} | "
            f"DRM_HYPERV built-in: {is_built_in} | "
            f"hyperv_drm in lsmod: {has_hyperv_drm} | "
            f"hyperv_fb in lsmod: {has_hyperv_fb}"
        )

    @TestCaseMetadata(
        description="""
        This case is to check whether the dri node is populated correctly.
        If hyperv_drm driver is bind correctly it should populate dri node.
        This dri node can be find at following sysfs entry : /sys/kernel/debug/dri/0.
        The dri node name (/sys/kernel/debug/dri/0/name) should contain `hyperv_drm`.

        Step,
        1. Cat /sys/kernel/debug/dri/0/name.
        2. Verify it contains hyperv_drm string in it.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_dri_node(self, node: Node, log: Logger) -> None:
        cat = node.tools[Cat]
        dri_path = "/sys/kernel/debug/dri/*/name"
        dri_name = cat.read(dri_path, sudo=True, force_run=True)
        assert_that(dri_name).described_as(
            "dri node not populated for hyperv_drm"
        ).matches("hyperv_drm")

    @TestCaseMetadata(
        description="""
        This case is to check this patch
        https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/commit/?id=19b5e6659eaf537ebeac90ae30c7df0296fe5ab9   # noqa: E501

        Step,
        1. Get dmesg output.
        2. Check no 'Unable to send packet via vmbus' shown up in dmesg output.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_no_error_output(self, node: Node, log: Logger) -> None:
        assert_that(node.tools[Dmesg].get_output(force_run=True)).described_as(
            "this error message is not expected to be seen "
            "if dirt_needed default value is set as false"
        ).does_not_contain("Unable to send packet via vmbus")

    @TestCaseMetadata(
        description="""
        This case is to check connector status using modetest utility for drm.

        Step,
        1. Install tool modetest.
        2. Verify the status return from modetest is connected.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_connection_status(self, node: Node, log: Logger) -> None:
        is_status_connected = node.tools[Modetest].is_status_connected("hyperv_drm")
        assert_that(is_status_connected).described_as(
            "dri connector status should be 'connected'"
        ).is_true()

    # def before_case(self, log: Logger, **kwargs: Any) -> None:
    #     node: Node = kwargs["node"]
    #     if isinstance(node.os, BSD) or isinstance(node.os, Windows):
    #         raise SkippedException(f"{node.os} is not supported.")

    #     if node.tools[KernelConfig].is_enabled("CONFIG_DRM_HYPERV"):
    #         log.debug(
    #             f"Current os {node.os.name} {node.os.information.version} "
    #             "supports DRM hyperv driver"
    #         )
    #         lsmod = node.tools[Lsmod]
    #         # hyperv_fb takes priority over hyperv_drm, so blacklist it
    #         if lsmod.module_exists("hyperv_fb"):
    #             echo = node.tools[Echo]
    #             echo.write_to_file(
    #                 "blacklist hyperv_fb",
    #                 node.get_pure_path("/etc/modprobe.d/blacklist-fb.conf"),
    #                 sudo=True,
    #             )
    #             node.tools[Reboot].reboot()

    #         # if the hyperv_fb is built-in, then we need to blacklist it in grub
    #         if lsmod.module_exists("hyperv_fb"):
    #             cat = node.tools[Cat]
    #             grub_content = "\n".join(
    #                 cat.run("/etc/default/grub").stdout.splitlines()
    #             )
    #             result = get_matched_str(
    #                 grub_content,
    #                 GRUB_CMDLINE_LINUX_DEFAULT_PATTERN,
    #                 first_match=False,
    #             ).replace("/", r"\/")

    #             sed = node.tools[Sed]

    #             sed.substitute(
    #                 regexp="GRUB_CMDLINE_LINUX_DEFAULT=.*",
    #                 replacement=f'GRUB_CMDLINE_LINUX_DEFAULT="{result} '
    #                 'module_blacklist=hyperv_fb"',
    #                 file="/etc/default/grub",
    #                 sudo=True,
    #             )

    #             if isinstance(node.os, Ubuntu):
    #                 node.execute("update-grub", sudo=True)
    #             elif isinstance(node.os, Fedora) or isinstance(node.os, Suse):
    #                 node.execute("grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True)
    #             # doesn't apply in debian as CONFIG_DRM_HYPERV isn't enabled in debian

    #             node.reboot(time_out=600)

    #     else:
    #         raise SkippedException(
    #             "DRM hyperv driver is not enabled in current distro"
    #             f" {node.os.name} {node.os.information.version}"
    #         )
