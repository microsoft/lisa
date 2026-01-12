# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Linux
from lisa.sut_orchestrator import HYPERV
from lisa.sut_orchestrator.hyperv.context import get_node_context
from lisa.testsuite import simple_requirement
from lisa.tools import FileSystem, KernelConfig, Mount, StressNg
from lisa.tools.hyperv import DynamicMemoryConfig, HyperV
from lisa.util import SkippedException


@dataclass
class DynamicMemoryTestContext:
    node: Node
    vm_name: str
    hyperv: HyperV
    dynamic_memory_config: DynamicMemoryConfig
    balloon_ready: bool
    hot_add_ready: bool
    page_size_kb: int
    host_guest_tolerance_mb: int = 512
    limit_tolerance_mb: int = 128


@TestSuiteMetadata(
    area="hyperv",
    category="functional",
    description="Validates Hyper-V dynamic memory behaviour on Linux guests",
    requirement=simple_requirement(
        supported_platform_type=[HYPERV],
        supported_os=[Linux],
    ),
)
class HyperVDynamicMemory(TestSuite):
    @TestCaseMetadata(
        description=(
            "Validates that with dynamic memory enabled, VM memory stress "
            "triggers hot add and increases assigned memory above the Startup "
            "Memory, while keeping host and guest memory aligned."
        ),
        priority=3,
    )
    def verify_dynamic_memory_hot_add(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hot_add(ctx)
        vm_gbytes = self._get_vm_stress_gbytes(ctx)
        self._apply_vm_stress(ctx, num_workers=64, vm_bytes=vm_gbytes, duration=30)
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction).described_as(
            "Hot add did not increase assigned memory under VM stress"
        ).is_greater_than(0)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description=(
            "Validates under huge page (mmaphuge) stress, dynamic memory "
            "increases assigned memory and AnonHugePages rises accordingly, "
            "keeping host and guest memory usage aligned."
        ),
        priority=3,
    )
    def verify_dynamic_memory_hot_add_hugepages(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hot_add(ctx)

        anon_huge_pages_before = self._read_meminfo_value(ctx.node, "AnonHugePages")
        mmap_gbytes = self._get_vm_stress_gbytes(ctx)
        anon_huge_pages_mid = self._apply_mmap_huge_stress(
            ctx,
            num_workers=64,
            mmap_bytes=mmap_gbytes,
            duration=30,
        )
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction).described_as(
            "Hot add did not increase assigned memory under stress with huge pages"
        ).is_greater_than(0)
        assert_that(anon_huge_pages_mid).described_as(
            "AnonHugePages did not increase under huge page stress"
        ).is_greater_than(anon_huge_pages_before)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description=(
            "Validates that dynamic memory increases assigned memory up to the "
            "configured maximum limit when the VM is under memory stress, while "
            "keeping host and guest memory usage aligned."
        ),
        priority=3,
    )
    def verify_dynamic_memory_upper_limit(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hot_add(ctx)
        vm_gbytes = self._get_vm_stress_gbytes(ctx)
        self._apply_vm_stress(ctx, num_workers=64, vm_bytes=vm_gbytes, duration=30)
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        net_mb_transaction = self._pages_to_mb(ctx, net_pages_transaction)
        expected_delta_mb = (
            ctx.dynamic_memory_config.maximum_mb - ctx.dynamic_memory_config.startup_mb
        )
        assert_that(net_mb_transaction).described_as(
            "assigned memory should be equal to maximum memory for VM under stress"
        ).is_close_to(expected_delta_mb, tolerance=ctx.limit_tolerance_mb)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description=(
            "Validates that under huge page (mmaphuge) stress, dynamic memory "
            "increases the VM's assigned memory up to the configured Maximum "
            "limit, while keeping host and guest memory usage aligned."
        ),
        priority=3,
    )
    def verify_dynamic_memory_upper_limit_hugepages(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hot_add(ctx)
        anon_huge_pages_before = self._read_meminfo_value(ctx.node, "AnonHugePages")
        mmap_gbytes = self._get_vm_stress_gbytes(ctx)
        anon_huge_pages_mid = self._apply_mmap_huge_stress(
            ctx,
            num_workers=64,
            mmap_bytes=mmap_gbytes,
            duration=30,
        )
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        net_mb_transaction = self._pages_to_mb(ctx, net_pages_transaction)
        expected_delta_mb = (
            ctx.dynamic_memory_config.maximum_mb - ctx.dynamic_memory_config.startup_mb
        )
        assert_that(net_mb_transaction).described_as(
            "assigned memory should be equal to maximum memory for VM under stress "
            "with huge pages"
        ).is_close_to(expected_delta_mb, tolerance=ctx.limit_tolerance_mb)
        assert_that(anon_huge_pages_mid).described_as(
            "AnonHugePages did not increase under huge page stress"
        ).is_greater_than(anon_huge_pages_before)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description=(
            "Validates that when the host is under memory pressure, the Hyper-V "
            "balloon driver inflates and reduces the VM's assigned memory while "
            "keeping host and guest memory usage aligned."
        ),
        priority=3,
    )
    def verify_dynamic_memory_balloon_up(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hv_balloon(ctx)
        net_pages_transaction_before = self._get_net_pages_transaction(ctx)
        host_pressure_mb = self._get_host_pressure_mb(ctx)
        ctx.hyperv.apply_memory_pressure(memory_mb=host_pressure_mb, duration=45)
        net_pages_transaction_after = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction_after).described_as(
            "Balloon up did not decrease assigned memory under host pressure"
        ).is_less_than(net_pages_transaction_before)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description=(
            "Validates that, under host memory pressure, dynamic memory reduces the "
            "VM's assigned memory down to the configured minimum limit when "
            "ballooning is enabled."
        ),
        priority=3,
    )
    def verify_dynamic_memory_lower_limit(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hv_balloon(ctx)
        host_pressure_mb = self._get_host_pressure_mb(ctx)
        ctx.hyperv.apply_memory_pressure(memory_mb=host_pressure_mb, duration=45)
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        net_mb_transaction = self._pages_to_mb(ctx, net_pages_transaction)
        expected_delta_mb = (
            ctx.dynamic_memory_config.minimum_mb - ctx.dynamic_memory_config.startup_mb
        )
        assert_that(net_mb_transaction).described_as(
            "Assigned memory should be equal to minimum memory for VM "
            "under host pressure"
        ).is_close_to(expected_delta_mb, tolerance=ctx.limit_tolerance_mb)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description=(
            "Validates balloon down behavior: applying VM memory stress deflates the "
            "balloon and increases the VM's assigned memory from the level before "
            "stress, while keeping host and guest memory usage aligned."
        ),
        priority=3,
    )
    def verify_dynamic_memory_balloon_down(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hv_balloon(ctx)
        host_pressure_mb = self._get_host_pressure_mb(ctx)
        ctx.hyperv.apply_memory_pressure(memory_mb=host_pressure_mb, duration=45)
        net_pages_transaction_before = self._get_net_pages_transaction(ctx)
        vm_gbytes = self._get_vm_stress_gbytes(ctx)
        self._apply_vm_stress(ctx, num_workers=64, vm_bytes=vm_gbytes, duration=45)
        net_pages_transaction_after = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction_after).described_as(
            "Assigned memory did not increase on VM under stress"
        ).is_greater_than(net_pages_transaction_before)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description=(
            "Validates balloon down with huge pages: mmaphuge stress deflates the "
            "balloon and raises assigned memory, with AnonHugePages increasing "
            "and keeping host and guest memory usage aligned."
        ),
        priority=3,
    )
    def verify_dynamic_memory_balloon_down_hugepages(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hv_balloon(ctx)
        host_pressure_mb = self._get_host_pressure_mb(ctx)
        ctx.hyperv.apply_memory_pressure(memory_mb=host_pressure_mb, duration=45)
        net_pages_transaction_before = self._get_net_pages_transaction(ctx)
        anon_huge_pages_before = self._read_meminfo_value(ctx.node, "AnonHugePages")
        mmap_gbytes = self._get_vm_stress_gbytes(ctx)
        anon_huge_pages_mid = self._apply_mmap_huge_stress(
            ctx,
            num_workers=64,
            mmap_bytes=mmap_gbytes,
            duration=45,
        )
        net_pages_transaction_after = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction_after).described_as(
            "Assigned memory did not increase on VM under stress with huge pages"
        ).is_greater_than(net_pages_transaction_before)
        assert_that(anon_huge_pages_mid).described_as(
            "AnonHugePages did not increase during huge page stress"
        ).is_greater_than(anon_huge_pages_before)
        self._validate_host_guest_alignment(ctx)

    def _get_context(
        self, node: Node, variables: Dict[str, Any]
    ) -> DynamicMemoryTestContext:
        node_context = get_node_context(node)

        if not node_context.host:
            raise SkippedException(
                "Hyper-V host context is required for Dynamic Memory Testsuite"
            )
        hyperv = node_context.host.tools[HyperV]
        dynamic_memory_config = hyperv.get_dynamic_memory_config(node_context.vm_name)
        if not dynamic_memory_config.dynamic_memory_enabled:
            raise SkippedException(
                "Dynamic memory is disabled on the Hyper-V host for this VM"
            )

        self._ensure_debugfs_mounted(node)

        kernel_config_balloon = node.tools[KernelConfig].is_enabled(
            "CONFIG_HYPERV_BALLOON"
        )
        kernel_config_hotplug = node.tools[KernelConfig].is_enabled(
            "CONFIG_MEMORY_HOTPLUG"
        )

        capabilities, page_size_kb = self._get_hv_balloon_info(node)
        capabilities = [cap.lower() for cap in capabilities]
        balloon_ready = (
            dynamic_memory_config.dynamic_memory_enabled
            and kernel_config_balloon
            and "enabled" in capabilities
        )
        hot_add_ready = (
            balloon_ready and kernel_config_hotplug and "hot_add" in capabilities
        )
        host_guest_tolerance_mb = int(variables.get("host_guest_tolerance_mb", 512))
        limit_tolerance_mb = int(variables.get("limit_tolerance_mb", 128))

        return DynamicMemoryTestContext(
            node=node,
            vm_name=node_context.vm_name,
            hyperv=hyperv,
            dynamic_memory_config=dynamic_memory_config,
            balloon_ready=balloon_ready,
            hot_add_ready=hot_add_ready,
            page_size_kb=page_size_kb,
            host_guest_tolerance_mb=host_guest_tolerance_mb,
            limit_tolerance_mb=limit_tolerance_mb,
        )

    def _get_vm_stress_gbytes(self, ctx: DynamicMemoryTestContext) -> str:
        max_mb = ctx.dynamic_memory_config.maximum_mb
        gbytes = math.ceil(math.ceil(max_mb * 1.75) / 1024)
        return f"{gbytes}G"

    def _get_host_pressure_mb(self, ctx: DynamicMemoryTestContext) -> int:
        host_total_memory_mb = ctx.hyperv.get_host_total_memory_mb()
        # We are running stress on host for 45 seconds; dividing total host memory by 45
        # sets a per-second stress rate. Over the 45s run, this approximates
        # consuming the host's total memory, reliably causing the host to ask
        # memory back from the VM (balloon up) without overcommitting.
        return math.ceil(host_total_memory_mb / 45)

    def _apply_vm_stress(
        self,
        ctx: DynamicMemoryTestContext,
        num_workers: int,
        vm_bytes: str,
        duration: int,
    ) -> None:
        stress_ng = ctx.node.tools[StressNg]
        stress_ng.launch_vm_stressor(
            num_workers=num_workers,
            vm_bytes=vm_bytes,
            timeout_in_seconds=duration,
        )

    def _apply_mmap_huge_stress(
        self,
        ctx: DynamicMemoryTestContext,
        num_workers: int,
        mmap_bytes: str,
        duration: int,
    ) -> int:
        """Run mmaphuge stress and optionally sample AnonHugePages mid-run."""
        stress_ng = ctx.node.tools[StressNg]
        process = stress_ng.launch_mmaphuge_stressor_async(
            num_workers=num_workers,
            mmap_bytes=mmap_bytes,
            timeout_in_seconds=duration,
        )

        wait_seconds = math.ceil(duration / 2)
        time.sleep(wait_seconds)
        mid_anon_huge_pages = self._read_meminfo_value(ctx.node, "AnonHugePages")

        process.wait_result(timeout=duration + 10)
        return mid_anon_huge_pages

    def _validate_host_guest_alignment(
        self,
        ctx: DynamicMemoryTestContext,
    ) -> None:
        mem_total_from_host_mb = ctx.hyperv.get_vm_memory_assigned_from_host(
            ctx.vm_name
        )
        mem_total_from_vm_mb = self._read_meminfo_value(ctx.node, "MemTotal") // 1024
        assert_that(mem_total_from_vm_mb).described_as(
            "Memory reported by Hyper-V host differs from guest MemTotal"
        ).is_close_to(mem_total_from_host_mb, tolerance=ctx.host_guest_tolerance_mb)

    def _read_meminfo_value(self, node: Node, key: str) -> int:
        content = node.execute("cat /proc/meminfo", sudo=False).stdout
        for line in content.splitlines():
            if line.startswith(key):
                value = line.split(":", 1)[1].strip().split()[0]
                return int(value)
        return 0

    def _pages_to_mb(
        self, ctx: DynamicMemoryTestContext, net_pages_transaction: int
    ) -> int:
        return (net_pages_transaction * ctx.page_size_kb) // 1024

    def _require_hv_balloon(self, ctx: DynamicMemoryTestContext) -> None:
        if not ctx.balloon_ready:
            raise SkippedException("Ballooning prerequisites not satisfied")

    def _require_hot_add(self, ctx: DynamicMemoryTestContext) -> None:
        if not ctx.hot_add_ready:
            raise SkippedException("Hot add prerequisites not satisfied")

    def _get_net_pages_transaction(self, ctx: DynamicMemoryTestContext) -> int:
        raw = self._read_hv_balloon_debugfs(ctx.node)
        data = self._parse_hv_balloon_debugfs(raw)

        pages_added = int(data.get("pages_added", "0") or 0)
        pages_ballooned = int(data.get("pages_ballooned", "0") or 0)
        return pages_added - pages_ballooned

    def _get_hv_balloon_info(self, node: Node) -> Tuple[List[str], int]:
        raw = self._read_hv_balloon_debugfs(node)
        data = self._parse_hv_balloon_debugfs(raw)

        capabilities_raw = data.get("capabilities", "")
        capabilities = capabilities_raw.split() if capabilities_raw else []
        page_size = int(data.get("page_size", "0") or 0)
        page_size_kb = page_size // 1024 if page_size else 0
        return capabilities, page_size_kb

    def _parse_hv_balloon_debugfs(self, raw: str) -> Dict[str, str]:
        data: Dict[str, str] = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue
            key, value = stripped.split(":", maxsplit=1)
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            if not normalized_key:
                continue
            data[normalized_key] = value.strip()
        return data

    def _read_hv_balloon_debugfs(self, node: Node) -> str:
        result = node.execute(
            "cat /sys/kernel/debug/hv-balloon",
            sudo=True,
            shell=True,
            no_info_log=True,
            no_debug_log=True,
            no_error_log=True,
        )
        if result.exit_code != 0 or not result.stdout:
            raise SkippedException(
                "Unable to read hv_balloon debugfs; ensure debugfs is mounted"
            )
        return result.stdout

    def _ensure_debugfs_mounted(self, node: Node) -> None:
        mount_tool = node.tools[Mount]
        if not mount_tool.check_mount_point_exist("/sys/kernel/debug"):
            mount_tool.mount(
                name="debugfs",
                point="/sys/kernel/debug",
                fs_type=FileSystem.debugfs,
            )
            if not mount_tool.check_mount_point_exist("/sys/kernel/debug"):
                raise SkippedException(
                    (
                        "Debugfs is not mounted and could not be mounted; "
                        "cannot access hv_balloon metrics"
                    )
                )
