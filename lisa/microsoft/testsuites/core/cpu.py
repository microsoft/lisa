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
        This test case checks that the L3 cache is correctly mapped to NUMA
        nodes, i.e. an L3 cache belongs to the NUMA node / socket it serves
        and is not incorrectly mapped to individual CPU cores.

        Steps:
        1. Check if NUMA is disabled in commandline. If disabled,
        and kernel version is <= 2.6.37, test is skipped as hyper-v
        has no support for NUMA : https://t.ly/x8k3
        2. Get the mappings using command :
        `lscpu --extended=cpu,node,socket,cache`
        3. Validate the L3 cache topology against these invariants
        (works for Intel 1:1, AMD EPYC multi-CCD and sub-NUMA clustering):
           a. An L3 cache must not span multiple sockets.
           b. If an L3 cache is shared across NUMA nodes, those NUMA nodes
              must be on the same socket (valid sub-NUMA clustering).
           c. L3 cache IDs must not be unique per CPU within a NUMA node
              (that indicates L3 is mapped to the CPU id instead of NUMA).
           d. In a strict 1:1 NUMA-to-L3 topology, the L3 cache id must
              equal the NUMA node id.

        If lscpu does not report a parseable cache mapping (e.g. ARM64 VMs
        without an L3 column, or partial cache reporting), the test is
        skipped instead of failed.

        Example failure modes (invariant 'd' / 'c'):
        Correct 1:1 mapping (L3 id == NUMA id):
        CPU NODE SOCKET L1d L1i L2 L3
        8   0    0      8   8   8  0
        9   1    1      9   9   9  1

        Incorrect mapping (L3 id == CPU id, not NUMA id):
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

        # Generic L3 cache topology validation for the remaining processor
        # types (after the known model/VM-size early returns above).
        # This handles both traditional 1:1 NUMA-to-L3 mapping (e.g. Intel)
        # and multi-L3-per-NUMA topologies (e.g. AMD EPYC where a NUMA node
        # spans multiple CCDs, each with its own L3 cache).
        #
        # The universal invariants verified are:
        # 1. L3 caches must not be shared across sockets
        # 2. Cross-NUMA L3 sharing is only valid within the same socket
        # 3. L3 cache IDs must not be unique per CPU (indicates L3=CPU_ID bug)
        # 4. In a strict 1:1 NUMA-to-L3 topology, L3 ID must equal NUMA ID
        try:
            cpu_info = lscpu.get_cpu_info()
        except AssertionError as e:
            # get_cpu_info() raises AssertionError when the lscpu output
            # cannot be parsed into the expected cache mapping format. This
            # happens on:
            # - VMs where no cache hierarchy is exposed (lscpu shows "-")
            # - ARM64 VMs that only have L1d/L1i/L2 (no L3)
            # - Partially allocated VMs where some NUMA nodes lack L3
            # - Any other unexpected/empty lscpu output
            raise SkippedException(
                f"Unable to parse lscpu cache mapping; cannot validate L3 "
                f"cache topology. Details: {e}"
            ) from e

        self._verify_l3_cache_topology(cpu_info, log)

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
        try:
            cpu_info = node.tools[Lscpu].get_cpu_info()
        except AssertionError as e:
            raise SkippedException(
                f"Unable to parse lscpu cache mapping; cannot validate L3 "
                f"cache topology. Details: {e}"
            ) from e
        cpu_info.sort(key=lambda cpu: cpu.cpu)
        for i, cpu in enumerate(cpu_info):
            numa_node_id = i // numa_node_size
            assert_that(
                cpu.l3_cache,
                "L3 cache of each core must be mapped to the NUMA node "
                "associated with the core.",
            ).is_equal_to(numa_node_id)

    def _verify_l3_cache_topology(
        self,
        cpu_info: list[Any],
        log: Logger,
    ) -> None:
        """Verify L3 cache topology is correct for any processor type.

        This is a generic validation that works for all topologies:
        - Traditional 1:1 NUMA-to-L3 (e.g. Intel, older AMD)
        - Multi-L3-per-NUMA (e.g. AMD EPYC where NUMA spans multiple CCDs)
        - Multi-NUMA-per-L3 (e.g. large VMs with sub-NUMA clustering where
          the hypervisor splits a socket into sub-NUMA domains but the
          physical L3 cache spans both NUMAs within the socket)

        The invariants verified are:
        1. L3 caches must not be shared across sockets
        2. If an L3 cache is shared across NUMA nodes, those NUMA nodes
           must be on the same socket
        3. L3 cache IDs must not be unique per CPU within a NUMA node
           (which would indicate L3 is incorrectly mapped to CPU ID)
        4. In a strict 1:1 NUMA-to-L3 topology, the L3 cache ID must
           equal the NUMA node ID
        """
        # Build helper mappings
        numa_to_l3_caches: dict[int, set[int]] = {}
        numa_to_sockets: dict[int, set[int]] = {}
        l3_to_numas: dict[int, set[int]] = {}
        l3_to_sockets: dict[int, set[int]] = {}
        for cpu in cpu_info:
            numa_to_l3_caches.setdefault(cpu.numa_node, set()).add(cpu.l3_cache)
            numa_to_sockets.setdefault(cpu.numa_node, set()).add(cpu.socket)
            l3_to_numas.setdefault(cpu.l3_cache, set()).add(cpu.numa_node)
            l3_to_sockets.setdefault(cpu.l3_cache, set()).add(cpu.socket)

        # 1. Verify no L3 cache is shared across sockets
        for l3_cache, sockets in l3_to_sockets.items():
            assert_that(
                len(sockets),
                f"L3 cache {l3_cache} must not span multiple sockets, "
                f"but is present on sockets {sorted(sockets)}",
            ).is_equal_to(1)

        # 2. If an L3 is shared across NUMA nodes, verify those NUMAs
        #    are on the same socket (sub-NUMA clustering is valid)
        for l3_cache, numas in l3_to_numas.items():
            if len(numas) <= 1:
                continue
            # Get all sockets these NUMA nodes belong to
            sockets_for_shared_l3: set[int] = set()
            for numa in numas:
                sockets_for_shared_l3.update(numa_to_sockets[numa])
            assert_that(
                len(sockets_for_shared_l3),
                f"L3 cache {l3_cache} is shared across NUMA nodes "
                f"{sorted(numas)}, but they span multiple sockets "
                f"{sorted(sockets_for_shared_l3)}. L3 sharing across "
                f"NUMA nodes is only valid within the same socket.",
            ).is_equal_to(1)

        # 3. Sanity check: if every CPU in a NUMA node has a unique L3
        #    cache, the L3 IDs are likely incorrectly mapped to CPU IDs
        #    instead of shared cache IDs. Valid multi-CCD topologies have
        #    fewer L3 caches than CPUs (e.g. 32 CPUs sharing 4 L3s).
        numa_to_cpus: dict[int, list[int]] = {}
        for cpu in cpu_info:
            numa_to_cpus.setdefault(cpu.numa_node, []).append(cpu.cpu)
        for numa_node, l3_caches in numa_to_l3_caches.items():
            cpu_count = len(numa_to_cpus.get(numa_node, []))
            if cpu_count > 1 and len(l3_caches) == cpu_count:
                assert_that(
                    len(l3_caches),
                    f"NUMA node {numa_node} has {cpu_count} CPUs each with "
                    f"a unique L3 cache ID {sorted(l3_caches)}, which "
                    f"indicates incorrect cache mapping (L3 should be "
                    f"shared across cores, not unique per CPU).",
                ).is_less_than(cpu_count)

        # 4. Strict 1:1 case: each NUMA owns exactly one L3 and each L3
        #    belongs to exactly one NUMA. Then L3 ID must equal NUMA ID.
        #    Multi-CCD and sub-NUMA clustering are excluded by this guard.
        each_numa_has_one_l3 = all(len(l3s) == 1 for l3s in numa_to_l3_caches.values())
        each_l3_has_one_numa = all(len(numas) == 1 for numas in l3_to_numas.values())
        if each_numa_has_one_l3 and each_l3_has_one_numa:
            for numa_node, l3_caches in numa_to_l3_caches.items():
                l3_cache = next(iter(l3_caches))
                assert_that(
                    l3_cache,
                    f"NUMA node {numa_node} maps 1:1 to a single L3 cache, "
                    f"so its L3 cache ID must equal the NUMA node ID, but "
                    f"got L3 cache ID {l3_cache}.",
                ).is_equal_to(numa_node)

        # Log the topology for debugging
        for numa_node, l3_caches in sorted(numa_to_l3_caches.items()):
            sorted_sockets = sorted(numa_to_sockets[numa_node])
            log.debug(
                f"NUMA node {numa_node} (socket {sorted_sockets}): "
                f"{len(l3_caches)} L3 cache(s) {sorted(l3_caches)}"
            )
        for l3_cache, numas in sorted(l3_to_numas.items()):
            if len(numas) > 1:
                log.debug(
                    f"L3 cache {l3_cache}: shared across NUMA nodes "
                    f"{sorted(numas)} (sub-NUMA clustering)"
                )
