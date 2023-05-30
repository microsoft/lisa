# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import time

from assertpy.assertpy import assert_that

from lisa import (
    LisaException,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import CpuArchitecture
from lisa.tools import Cat, InterruptInspector, Lscpu, TaskSet, Uname

hyperv_interrupt_substr = ["hyperv", "Hypervisor", "Hyper-V"]


EPYC_ROME_NUMA_NODE_SIZE = 4
EPYC_MILAN_NUMA_NODE_SIZE = 8


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite is used to run CPU related tests.
    """,
)
class CPU(TestSuite):
    @TestCaseMetadata(
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
    def verify_l3_cache(self, node: Node, log: Logger) -> None:
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

        lscpu = node.tools[Lscpu]
        threads_per_core = lscpu.get_thread_per_core_count()
        processor_name = lscpu.get_cpu_model_name()

        if processor_name:
            if "7452" in processor_name:
                # This is AMD EPYC Rome processor series
                effective_numa_node_size = EPYC_ROME_NUMA_NODE_SIZE * threads_per_core
                self._verify_node_mapping(node, effective_numa_node_size)
                return
            elif "7763" in processor_name:
                # This is AMD EPYC Milan processor series
                effective_numa_node_size = EPYC_MILAN_NUMA_NODE_SIZE * threads_per_core
                self._verify_node_mapping(node, effective_numa_node_size)
                return

        cpu_info = lscpu.get_cpu_info()
        for cpu in cpu_info:
            assert_that(
                cpu.l3_cache,
                "L3 cache of each core must be mapped to the NUMA node "
                "associated with the core.",
            ).is_equal_to(cpu.numa_node)

    @TestCaseMetadata(
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
    def verify_cpu_count(self, node: Node, log: Logger) -> None:
        lscpu = node.tools[Lscpu]
        # 1. Get vCPU count.
        cpu_count = lscpu.get_core_count()
        log.debug(f"{cpu_count} CPU cores detected...")
        # 2. Calculate vCPU count
        calculated_cpu_count = lscpu.calculate_vcpu_count()
        # 3. Judge whether the actual vCPU count equals to expected value.
        assert_that(cpu_count).described_as(
            "The VM may end up being incorrectly configured on some Azure hosts,"
            " it is a known host bug, please check the host version."
        ).is_equal_to(calculated_cpu_count)

    @TestCaseMetadata(
        description="""
            This test will verify if the CPUs inside a Linux VM are processing VMBus
            interrupts by checking the /proc/interrupts file.

            There are 3 types of Hyper-v interrupts : Hypervisor callback
            interrupts, Hyper-V reenlightenment interrupts, and Hyper-V stimer0
            interrupts, these types not shown up in arm64 arch.

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
        interrupt_inspector = node.tools[InterruptInspector]
        interrupts = interrupt_inspector.get_interrupt_data()
        for interrupt in interrupts:
            is_hyperv_interrupt = any(
                [(substr in interrupt.metadata) for substr in hyperv_interrupt_substr]
            )
            if not is_hyperv_interrupt:
                continue
            log.debug(f"Processing Hyper-V interrupt : {interrupt}")
            assert_that(
                len(interrupt.cpu_counter),
                "Hyper-v interrupts should have count for each cpu.",
            ).is_equal_to(cpu_count)
            if interrupt.irq_number == "HRE" or "reenlightenment" in interrupt.metadata:
                assert_that(
                    all(
                        [
                            interrupt_count == 0
                            for interrupt_count in interrupt.cpu_counter
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
                            for interrupt_count in interrupt.cpu_counter
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
                            for interrupt_count in interrupt.cpu_counter
                        ]
                    ),
                    "Hypervisor synthetic timer interrupt should be processed by "
                    "all vCPU's",
                ).is_equal_to(True)
            else:
                continue

            found_hyperv_interrupt = True

        arch = node.os.get_kernel_information().hardware_platform  # type: ignore
        # Fail test execution if these hyper-v interrupts are not showing up
        if arch != CpuArchitecture.ARM64 and not found_hyperv_interrupt:
            raise LisaException("Hyper-V interrupts are not recorded.")

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

    def _verify_node_mapping(self, node: Node, numa_node_size: int) -> None:
        cpu_info = node.tools[Lscpu].get_cpu_info()
        cpu_info.sort(key=lambda cpu: cpu.cpu)
        for i, cpu in enumerate(cpu_info):
            numa_node_id = i // numa_node_size
            assert_that(
                cpu.l3_cache,
                "L3 cache of each core must be mapped to the NUMA node "
                "associated with the core.",
            ).is_equal_to(numa_node_id)
