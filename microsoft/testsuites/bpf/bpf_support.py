# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from assertpy.assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner
from lisa.testsuite import simple_requirement
from lisa.tools.ls import Ls
from lisa.tools.lsmod import Lsmod


@TestSuiteMetadata(
    area="bpf",
    category="functional",
    description="""
    This test suite is to confirm bpf support.
    """,
)
class BpfSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case checks for the presences of the btf sysfs.
        It checks if the /sys/kernel/btf/vmlinux file exists and if any loaded kernel
        modules have corresponding entries in the /sys/kernel/btf directory.

        If both conditions are met, it confirms that BTF (BPF Type Format) data is
        available on the system.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def confirm_btf_sysfs(
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

        # Check if module is available in /sys/kernel/btf
        for module in modules:
            result = ls.path_exists(f"/sys/kernel/btf/{module}", sudo=True)
            assert_that(
                result,
                description=f"Check if /sys/kernel/btf/{module} exists",
            ).is_equal_to(True)

        # If all checks passed, log success
        log.info("BTF sysfs confirmed for all loaded modules.")
