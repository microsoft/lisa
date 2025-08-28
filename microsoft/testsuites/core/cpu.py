# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import time
from typing import Any

from assertpy.assertpy import assert_that

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
from lisa.environment import Environment
from lisa.operating_system import BSD, CpuArchitecture, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import AzureNodeSchema
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.tools import Cat, InterruptInspector, Lscpu, TaskSet, Uname

hyperv_interrupt_substr = ["hyperv", "hypervsum", "Hypervisor", "Hyper-V"]


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
        priority=1,
        # Marking this test unsupported on BSD as the neccessary info is not exposed
        requirement=simple_requirement(
            unsupported_os=[Windows, BSD],
        ),
    )
    def verify_l3_cache(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
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

        # Standard_NC8as_T4_v3 and Standard_NC16as_T4_v3 has all the cores
        # mapped to a single L3 cache. This a known Host Bug and we do not
        # have an ETA on when the fix will be released.
        # This is a temporary exception for this VM size and needs to be
        # reverted when the Host fix is released.
        if isinstance(environment.platform, AzurePlatform):
            node_capability = node.capability.get_extended_runbook(
                AzureNodeSchema, AZURE
            )
            if node_capability.vm_size in [
                "Standard_NC8as_T4_v3",
                "Standard_NC16as_T4_v3",
            ]:
                self._verify_node_mapping(node, 16)
                return

        if processor_name:
            # ND A100 v4-series and NDm A100 v4-series
            # CPU type is "AMD EPYC 7V12 (Rome)"
            if "7452" in processor_name or "7V12" in processor_name:
                # This is AMD EPYC Rome processor series
                effective_numa_node_size = EPYC_ROME_NUMA_NODE_SIZE * threads_per_core
                self._verify_node_mapping(node, effective_numa_node_size)
                return
            elif "7763" in processor_name:
                # This is AMD EPYC Milan processor series
                effective_numa_node_size = EPYC_MILAN_NUMA_NODE_SIZE * threads_per_core
                self._verify_node_mapping(node, effective_numa_node_size)
                return

        # For all other cases, check L3 cache mapping with socket awareness
        cpu_info = lscpu.get_cpu_info()

        # Build a mapping of socket -> NUMA nodes and socket -> L3 caches
        socket_to_numa_nodes: dict[int, set[int]] = {}
        socket_to_l3_caches: dict[int, set[int]] = {}

        for cpu in cpu_info:
            socket = cpu.socket
            numa_node = cpu.numa_node
            l3_cache = cpu.l3_cache

            # Track NUMA nodes per socket
            if socket not in socket_to_numa_nodes:
                socket_to_numa_nodes[socket] = set()
            socket_to_numa_nodes[socket].add(numa_node)

            # Track L3 caches per socket
            if socket not in socket_to_l3_caches:
                socket_to_l3_caches[socket] = set()
            socket_to_l3_caches[socket].add(l3_cache)

        # Check if this is a simple 1:1 mapping (traditional case)
        all_numa_nodes = set()
        all_l3_caches = set()
        for numa_nodes in socket_to_numa_nodes.values():
            all_numa_nodes.update(numa_nodes)
        for l3_caches in socket_to_l3_caches.values():
            all_l3_caches.update(l3_caches)

        # Check if this is a simple 1:1 mapping or socket-aware mapping
        # If NUMA nodes and L3 caches are identical sets, use simple verification
        if self._is_one_to_one_mapping(socket_to_numa_nodes, socket_to_l3_caches):
            self._verify_one_to_one_mapping(cpu_info, log)
        else:
            self._verify_socket_aware_mapping(
                cpu_info, socket_to_numa_nodes, socket_to_l3_caches, log
            )

    @TestCaseMetadata(
        description="""
            This test will check that vCPU count correctness.
            Steps :
            1. Get vCPU count.
            2. Calculate vCPU count by core_per_socket_count * socket_count *
             thread_per_core_count.
            3. Judge whether the actual vCPU count equals to expected value.
            """,
        priority=1,
        requirement=simple_requirement(unsupported_os=[]),
    )
    def verify_cpu_count(self, node: Node, log: Logger) -> None:
        lscpu = node.tools[Lscpu]
        # 1. Get vCPU count.
        thread_count = lscpu.get_thread_count()
        log.debug(f"{thread_count} CPU threads detected...")
        # 2. Calculate vCPU count
        calculated_cpu_count = lscpu.calculate_vcpu_count()
        # 3. Judge whether the actual vCPU count equals to expected value.
        assert_that(thread_count).described_as(
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
            3. For Hypervisor callback interrupt, verify that at least min(#vCPU, 4)
            vCPU's are processing interrupts.
            4. For Hyper-V Synthetic timer, run a CPU intensive command on each vCPU and
            verify that every vCPU is processing the interrupt.
            """,
        priority=2,
    )
    def verify_vmbus_interrupts(self, node: Node, log: Logger) -> None:
        found_hyperv_interrupt = False
        thread_count = node.tools[Lscpu].get_thread_count()
        log.debug(f"{thread_count} CPU threads detected...")

        self._create_stimer_interrupts(node, thread_count)
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
            ).is_equal_to(thread_count)
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
                ).is_greater_than_or_equal_to(min(thread_count, 4))
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
            elif isinstance(node.os, BSD):
                assert_that(
                    all(
                        [
                            interrupt_count > 0
                            for interrupt_count in interrupt.cpu_counter
                        ]
                    ),
                    "Hypervisor interrupts should be processed by all vCPU's",
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

    def _is_one_to_one_mapping(
        self,
        socket_to_numa_nodes: dict[int, set[int]],
        socket_to_l3_caches: dict[int, set[int]],
    ) -> bool:
        """Check if NUMA nodes and L3 caches have a 1:1 mapping."""
        all_numa_nodes = set()
        all_l3_caches = set()
        for numa_nodes in socket_to_numa_nodes.values():
            all_numa_nodes.update(numa_nodes)
        for l3_caches in socket_to_l3_caches.values():
            all_l3_caches.update(l3_caches)

        return all_numa_nodes == all_l3_caches

    def _verify_one_to_one_mapping(self, cpu_info: list[Any], log: Logger) -> None:
        """Verify traditional 1:1 mapping between NUMA nodes and L3 caches."""
        log.debug("Detected 1:1 mapping between NUMA nodes and L3 caches")
        for cpu in cpu_info:
            assert_that(
                cpu.l3_cache,
                "L3 cache of each core must be mapped to the NUMA node "
                "associated with the core.",
            ).is_equal_to(cpu.numa_node)

    def _verify_socket_aware_mapping(
        self,
        cpu_info: list[Any],
        socket_to_numa_nodes: dict[int, set[int]],
        socket_to_l3_caches: dict[int, set[int]],
        log: Logger,
    ) -> None:
        """Verify shared L3 cache mapping within sockets."""
        log.debug("Detected shared L3 cache within sockets")

        # Verify consistency: all CPUs in same NUMA node should have same L3 cache
        self._verify_numa_consistency(cpu_info)

        # Verify isolation: L3 caches should not be shared across sockets
        self._verify_socket_isolation(socket_to_numa_nodes, socket_to_l3_caches, log)

    def _verify_numa_consistency(self, cpu_info: list[Any]) -> None:
        """Verify all CPUs in the same NUMA node have the same L3 cache."""
        numa_to_l3_mapping = {}
        for cpu in cpu_info:
            if cpu.numa_node not in numa_to_l3_mapping:
                numa_to_l3_mapping[cpu.numa_node] = cpu.l3_cache
            else:
                # Verify consistency: all CPUs in same NUMA node should have same L3
                assert_that(
                    cpu.l3_cache,
                    f"All CPUs in NUMA node {cpu.numa_node} should have the same "
                    f"L3 cache mapping, expected "
                    f"{numa_to_l3_mapping[cpu.numa_node]} "
                    f"but found {cpu.l3_cache} for CPU {cpu.cpu}",
                ).is_equal_to(numa_to_l3_mapping[cpu.numa_node])

    def _verify_socket_isolation(
        self,
        socket_to_numa_nodes: dict[int, set[int]],
        socket_to_l3_caches: dict[int, set[int]],
        log: Logger,
    ) -> None:
        """Verify L3 caches are not shared across sockets."""
        for socket, numa_nodes in socket_to_numa_nodes.items():
            l3_caches_in_socket = socket_to_l3_caches[socket]

            # Get L3 caches used by other sockets
            other_socket_l3_caches = set()
            for other_socket, other_l3_caches in socket_to_l3_caches.items():
                if other_socket != socket:
                    other_socket_l3_caches.update(other_l3_caches)

            # Verify no L3 cache is shared across sockets
            shared_l3_caches = l3_caches_in_socket.intersection(other_socket_l3_caches)
            assert_that(
                len(shared_l3_caches),
                f"L3 caches should not be shared across sockets. "
                f"Socket {socket} shares L3 cache(s) {shared_l3_caches} with "
                f"other sockets",
            ).is_equal_to(0)

            log.debug(
                f"Socket {socket}: NUMA nodes {sorted(numa_nodes)} use "
                f"L3 cache(s) {sorted(l3_caches_in_socket)}"
            )
