# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any

from assertpy.assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner
from lisa.tools.ls import Ls
from lisa.tools.lsmod import Lsmod
from lisa.util import SkippedException, UnsupportedDistroException


@TestSuiteMetadata(
    area="bpf",
    category="functional",
    description="""
    This test suite is to confirm bpf support.
    """,
)
class BpfSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "3.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "BPF support promised on AzureLinux 3.0 and later."
                )
            )

    @TestCaseMetadata(
        description="""
        This test case checks for the presences of the btf sysfs.
        It checks if the /sys/kernel/btf/vmlinux file exists and if any loaded kernel
        modules have corresponding entries in the /sys/kernel/btf directory.

        If both conditions are met, it confirms that BTF (BPF Type Format) data is
        available on the system.
        """,
        priority=3,
    )
    def verify_btf_sysfs_exists(
        self,
        node: Node,
        log: Logger,
    ) -> None:
        # Check if /sys/kernel/btf/vmlinux exists
        ls = node.tools[Ls]
        lsmod = node.tools[Lsmod]
        result = ls.path_exists("/sys/kernel/btf/vmlinux", sudo=True)
        assert_that(
            result,
            description="Check if /sys/kernel/btf/vmlinux exists",
        ).is_equal_to(True)
        log.info("BTF sysfs confirmed for /sys/kernel/btf/vmlinux.")

        # Grab loaded modules
        modules = lsmod.list_modules()

        missing_modules = []

        for module in modules:
            result = ls.path_exists(f"/sys/kernel/btf/{module}", sudo=True)
            if not result:
                missing_modules.append(module)

        if missing_modules:
            log.error("BTF sysfs missing for modules: %s", ", ".join(missing_modules))

        assert_that(
            missing_modules,
            description=(
                "The following modules are missing /sys/kernel/btf entries: "
                f"{', '.join(missing_modules)}"
            ),
        ).is_empty()

        log.info("BTF sysfs confirmed for all loaded modules.")
