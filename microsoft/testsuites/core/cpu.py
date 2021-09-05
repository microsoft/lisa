# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath

from assertpy.assertpy import assert_that

from lisa import (
    BadEnvironmentStateException,
    LisaException,
    Logger,
    Node,
    SkippedException,
    testsuite,
)
from lisa.tools import Cat, Echo, Lscpu, Lsvmbus, Uname


class CPUState:
    OFFLINE: str = "0"
    ONLINE: str = "1"


@testsuite.TestSuiteMetadata(
    area="cpu",
    category="functional",
    description="""
    This test suite is used to run CPU related tests.
    """,
)
class CPU(testsuite.TestSuite):
    def _get_cpu_config_file(self, cpu_id: str) -> str:
        return f"/sys/devices/system/cpu/cpu{cpu_id}/online"

    def _set_cpu_state(self, cpu_id: str, state: str, node: Node) -> bool:
        file_path = self._get_cpu_config_file(cpu_id)
        node.tools[Echo].write_to_file(state, file_path, sudo=True)
        result = node.tools[Cat].read_from_file(file_path, force_run=True, sudo=True)
        return result == state

    @testsuite.TestCaseMetadata(
        description="""
            This test will check that CPU assigned to lsvmbus
            channels cannot be put offline.
            Steps :
            1. Get the list of lsvmbus channel cpu mappings using
            command `lsvmbus -vv`.
            2. Create a set of cpu's assigned to lsvmbus channels.
            3. Try to put cpu offline by running
            `echo 0 > /sys/devices/system/cpu/cpu/<cpu_id>/online`.
            Note : We skip cpu 0 as it handles system interrupts.
            4. Ensure that cpu is still online by checking state '1' in
            `/sys/devices/system/cpu/cpu/<target_cpu>/online`.
            """,
        priority=2,
    )
    def cpu_verify_vmbus_force_online(self, node: Node, log: Logger) -> None:
        cpu_count = node.tools[Lscpu].get_core_count()
        log.debug(f"{cpu_count} CPU cores detected...")

        # Find CPUs(except CPU0) which are mapped to LSVMBUS channels and have
        # `sys/devices/system/cpu/cpu/cpu<id>/online` file present.
        channels = node.tools[Lsvmbus].get_device_channels_from_lsvmbus()
        is_non_zero_cpu_id_mapped = False
        mapped_cpu_set = set()
        for channel in channels:
            for channel_vp_map in channel.channel_vp_map:
                target_cpu = channel_vp_map.target_cpu
                if target_cpu == "0":
                    continue
                is_non_zero_cpu_id_mapped = True
                file_path = self._get_cpu_config_file(target_cpu)
                file_exists = node.shell.exists(PurePosixPath(file_path))
                if file_exists:
                    mapped_cpu_set.add(target_cpu)

        # Fail test if `/sys/devices/system/cpu/cpu/cpu<id>/online` file does
        # not exist for all CPUs(except CPU0) mapped to LSVMBUS channels. This
        # is to catch distros which have this unexpected behaviour.
        if is_non_zero_cpu_id_mapped and not mapped_cpu_set:
            raise LisaException(
                "/sys/devices/system/cpu/cpu/cpu<id>/online file"
                "does not exists for all CPUs mapped to LSVMBUS channels."
            )

        for target_cpu in mapped_cpu_set:
            log.debug(f"Checking CPU {target_cpu} on /sys/device/....")
            result = self._set_cpu_state(target_cpu, CPUState.OFFLINE, node)
            if result:
                # Try to bring CPU back to it's original state
                reset = self._set_cpu_state(target_cpu, CPUState.ONLINE, node)
                exception_message = (
                    f"Expected CPU {target_cpu} state : {CPUState.ONLINE}(online), "
                    f"actual state : {CPUState.OFFLINE}(offline). CPU's mapped to "
                    f"LSVMBUS channels shouldn't be in state "
                    f"{CPUState.OFFLINE}(offline)."
                )
                if not reset:
                    raise BadEnvironmentStateException(
                        exception_message,
                        f"The test failed leaving CPU {target_cpu} in a bad state.",
                    )
                raise AssertionError(exception_message)

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
        priority=2,
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

    @testsuite.TestCaseMetadata(
        description="""
            This test will check that vCPU count correctness.
            Steps :
            1. Get vCPU count.
            2. Calculate vCPU count by core_per_socket_count * socket_count *
             thread_per_core_count.
            3. Judge whether the actual vCPU count equals to expected value.
            """,
        priority=2,
    )
    def cpu_count_check(self, node: Node, log: Logger) -> None:
        lscpu = node.tools[Lscpu]
        # 1. Get vCPU count.
        cpu_count = lscpu.get_core_count()
        log.debug(f"{cpu_count} CPU cores detected...")
        # 2. Caculate vCPU count by core_per_socket_count * socket_count *
        #  thread_per_core_count.
        caculated_cpu_count = (
            lscpu.get_core_per_socket_count()
            * lscpu.get_socket_count()
            * lscpu.get_thread_per_core_count()
        )
        # 3. Judge whether the actual vCPU count equals to expected value.
        assert_that(cpu_count).described_as(
            "The VM may end up being incorrectly configured on some Azure hosts,"
            " it is a known host bug, please check the host version."
        ).is_equal_to(caculated_cpu_count)
