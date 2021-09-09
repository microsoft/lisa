# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List

from assertpy.assertpy import assert_that

from lisa import (
    BadEnvironmentStateException,
    LisaException,
    Logger,
    Node,
    SkippedException,
    testsuite,
)
from lisa.tools import Cat, Echo, Lscpu, Lsvmbus, TaskSet, Uname


class CPUState:
    OFFLINE: str = "0"
    ONLINE: str = "1"


hyperv_interrupt_substr = ["hyperv", "Hypervisor", "Hyper-V"]


@dataclass
class Interrupt:
    irq_number: str
    interrupt_count: List[int]
    metadata: str

    # 0:         22          0  IR-IO-APIC   2-edge      timer
    _interrupt_regex = re.compile(
        r"^\s*(?P<irq_number>\S+):\s+(?P<interrupt_count>[\d+ ]+)\s*(?P<metadata>.*)$"
    )

    def __init__(
        self, irq_number: str, interrupt_count: List[int], metadata: str = ""
    ) -> None:
        self.irq_number = irq_number
        self.interrupt_count = interrupt_count
        self.metadata = metadata

    def __str__(self) -> str:
        return (
            f"irq_number : {self.irq_number}, "
            f"count : {self.interrupt_count}, "
            f"metadata : {self.metadata}"
        )

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def get_interrupt_data(node: Node) -> List[Interrupt]:
        # Run cat /proc/interrupts. The output is of the form :
        #          CPU0       CPU1
        # 0:         22          0  IR-IO-APIC   2-edge      timer
        # 1:          2          0  IR-IO-APIC   1-edge      i8042
        # ERR:        0
        # The first column refers to the IRQ number. The next column contains
        # number of interrupts per IRQ for each CPU in the system. The remaining
        # column report the metadata about interrupts, including type of interrupt,
        # device etc. This is variable for each distro.
        # Note : Some IRQ numbers have single entry because they're not actually
        # CPU stats, but events count belonging to the IO-APIC controller. For
        # example, `ERR` is incremented in the case of errors in the IO-APIC bus.
        result = node.tools[Cat].run("/proc/interrupts", sudo=True).stdout
        mappings_with_header = result.splitlines(keepends=False)
        mappings = mappings_with_header[1:]
        assert len(mappings) > 0

        interrupts = []
        for line in mappings:
            matched = Interrupt._interrupt_regex.fullmatch(line)
            assert matched
            interrupt_count = [
                int(count) for count in matched.group("interrupt_count").split()
            ]
            interrupts.append(
                Interrupt(
                    irq_number=matched.group("irq_number"),
                    interrupt_count=interrupt_count,
                    metadata=matched.group("metadata"),
                )
            )
        return interrupts


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

    @testsuite.TestCaseMetadata(
        description="""
            This test will verify if the CPUs inside a Linux VM are processing VMBus
            interrupts by checking the /proc/interrupts file.

            There are 3 types of Hyper-v interrupts : Hypervisor callback
            interrupts, Hyper-V reenlightenment interrupts, and Hyper-V stimer0
            interrupts.

            Hyper-V reenlightenment interrupts are 0 unless the VM is doing migration.

            Hypervisor callback interrupts are vmbus events that are generated on all
            the vmbus channels, which belong to different vmbus devices. A VM with upto
            4 vcpu on Azure/Hyper-V should have a NetVSC NIC, which normally has 4 VMBus
            channel and should be bound to all the vCPUs.

            Hyper-V Synthetic timer interrupts should be received on each CPU if the VM
            is run for a long time. We can simulate this process by running CPU
            intensive workload on each vCPU.

            Steps:
            1. Look for the Hyper-v timer property of each vCPU under /proc/interrupts
            2. For Hyper-V reenlightenment interrupt, verify that the interrupt count
            for all vCPU are zero.
            3. For Hypervisor callback interrupt, verify that atleast min(#vCPU, 4)
            vCPU's are processing interrupts.
            4. For Hyper-V Synthetic timer, run a CPU intensive command on each vCPU and
            verify that every vCPU is processing the interrupt.
            """,
        priority=2,
    )
    def verify_vmbus_interrupts(self, node: Node, log: Logger) -> None:
        found_hyperv_interrupt = False
        cpu_count = node.tools[Lscpu].get_core_count()
        log.debug(f"{cpu_count} CPU cores detected...")

        self._create_stimer_interrupts(node, cpu_count)
        interrupts = Interrupt.get_interrupt_data(node)
        for interrupt in interrupts:
            is_hyperv_interrupt = any(
                [(substr in interrupt.metadata) for substr in hyperv_interrupt_substr]
            )
            if not is_hyperv_interrupt:
                continue
            log.debug(f"Processing Hyper-V interrupt : {interrupt}")
            assert_that(
                len(interrupt.interrupt_count),
                "Hyper-v interrupts should have count for each cpu.",
            ).is_equal_to(cpu_count)
            if interrupt.irq_number == "HRE" or "reenlightenment" in interrupt.metadata:
                assert_that(
                    all(
                        [
                            interrupt_count == 0
                            for interrupt_count in interrupt.interrupt_count
                        ]
                    ),
                    "Hyper-V reenlightenment interrupts should be 0 on each vCPU "
                    "unless the VM is doing migration.",
                ).is_greater_than_or_equal_to(True)
            elif interrupt.irq_number == "HYP" or "callback" in interrupt.metadata:
                assert_that(
                    sum(
                        [
                            interrupt_count > 0
                            for interrupt_count in interrupt.interrupt_count
                        ]
                    ),
                    "Hypervisor callback interrupt should be processed by "
                    "atleast min(#vCPU, 4) vCPU's",
                ).is_greater_than_or_equal_to(min(cpu_count, 4))
            elif interrupt.irq_number == "HVS" or "stimer" in interrupt.metadata:
                assert_that(
                    all(
                        [
                            interrupt_count > 0
                            for interrupt_count in interrupt.interrupt_count
                        ]
                    ),
                    "Hypervisor synthetic timer interrupt should be processed by "
                    "all vCPU's",
                ).is_equal_to(True)
            else:
                continue

            found_hyperv_interrupt = True

        # Fail test execution if these hyper-v interrupts are not showing up
        if not found_hyperv_interrupt:
            raise LisaException("Hyper-V interrupts are not recorded.")

    def _get_cpu_config_file(self, cpu_id: str) -> str:
        return f"/sys/devices/system/cpu/cpu{cpu_id}/online"

    def _set_cpu_state(self, cpu_id: str, state: str, node: Node) -> bool:
        file_path = self._get_cpu_config_file(cpu_id)
        node.tools[Echo].write_to_file(state, file_path, sudo=True)
        result = node.tools[Cat].read_from_file(file_path, force_run=True, sudo=True)
        return result == state

    def _create_stimer_interrupts(self, node: Node, cpu_count: int) -> None:
        # Run CPU intensive workload to create hyper-v synthetic timer
        # interrupts.
        # Steps :
        # 1. Run `yes` program on each vCPU in a subprocess.
        # 2. Wait for one second to allow enough time for processing interrupts.
        # 3. Kill the spawned subprocess.
        for i in range(1, cpu_count):
            process = node.tools[TaskSet].run_on_specific_cpu(i)
            time.sleep(1)
            process.kill()
