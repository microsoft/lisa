# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy.assertpy import assert_that

from lisa import Logger, testsuite
from lisa.base_tools.cat import Cat
from lisa.base_tools.uname import Uname
from lisa.node import Node
from lisa.tools.lscpu import Lscpu
from lisa.util import SkippedException


@testsuite.TestSuiteMetadata(
    area="cpu",
    category="functional",
    description="""
    This test suite is used to run CPU related tests.
    """,
)
class CPU(testsuite.TestSuite):
    @testsuite.TestCaseMetadata(
        description="""
        This test case will check that L3 cache is correctly mapped
        to NUMA node.
        Steps:
        1. Check if NUMA is disabled in commandline. If disabled,
        and kernel version is <= 2.6.37, test is skipped as hyper-v
        has no support for NUMA : https://t.ly/x8k3
        2. Get the mappings using command :
        `lscpu --extended=cpu,node,socket,cache`
        3. Each line in the mapping corresponds to one CPU core. The L3
        cache of each core must be mapped to the NUMA node that core
        belongs to instead of the core itself.

        Example :
        Correct mapping:
        CPU NODE SOCKET L1d L1i L2 L3
        8   0    0      8   8   8  0
        9   1    1      9   9   9  1

        Incorrect mapping:
        CPU NODE SOCKET L1d L1i L2 L3
        8   0    0      8   8   8  8
        9   1    1      9   9   9  9
        """,
        priority=1,
    )
    def l3_cache_check(self, node: Node, log: Logger) -> None:
        cmdline = node.tools[Cat].run("/proc/cmdline").stdout
        if "numa=off" in cmdline:
            uname_result = node.tools[Uname].get_linux_information()
            log.debug("Found numa=off in /proc/cmdline. Checking the kernel version.")
            if uname_result.kernel_version <= "2.6.37":
                raise SkippedException(
                    f"kernel : {uname_result.kernel_version_raw} has numa=off in boot "
                    "parameter and its kernel version is earlier than 2.6.37. "
                    "No support for NUMA setting. https://t.ly/x8k3"
                )

        cpu_info = node.tools[Lscpu].get_cpu_info()
        for cpu in cpu_info:
            assert_that(
                cpu.l3_cache,
                "L3 cache of each core must be mapped to the NUMA node "
                "associated with the core.",
            ).is_equal_to(cpu.numa_node)
