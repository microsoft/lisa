# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.base_tools import Uname
from lisa.operating_system import Linux
from lisa.sut_orchestrator import HYPERV
from lisa.sut_orchestrator.hyperv.context import get_node_context
from lisa.testsuite import simple_requirement
from lisa.tools import StressNg
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
        description="""Validate hot add of dynamic memory""",
        priority=1,
    )
    def verify_dynamic_memory_hot_add(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hot_add(ctx)
        self._apply_vm_stress(ctx, num_workers=64, vm_bytes="25G", duration=30)
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction).described_as(
            "Hot add did not increase net pages transaction under VM stress"
        ).is_greater_than(0)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description="""Validate Upper limit of dynamic memory""",
        priority=1,
    )
    def verify_dynamic_memory_upper_limit(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hot_add(ctx)
        self._apply_vm_stress(ctx, num_workers=64, vm_bytes="25G", duration=30)
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        net_mb_transaction = self._pages_to_mb(ctx, net_pages_transaction)
        expected_delta_mb = (
            ctx.dynamic_memory_config.maximum_mb - ctx.dynamic_memory_config.startup_mb
        )
        assert_that(net_mb_transaction).described_as(
            "net_mb_transaction must equal maximum_memory_mb - startup_memory_mb"
        ).is_equal_to(expected_delta_mb)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description="""Validate Balloon Up under Host Memory Pressure""",
        priority=1,
    )
    def verify_dynamic_memory_balloon_up(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hv_balloon(ctx)
        net_pages_transaction_before = self._get_net_pages_transaction(ctx)
        ctx.hyperv.apply_memory_pressure(memory_mb=2048, duration=45)
        net_pages_transaction_after = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction_after).described_as(
            "Balloon up did not decrease net pages transaction under host pressure"
        ).is_less_than(net_pages_transaction_before)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description="""Validate Lower limit of dynamic memory""",
        priority=1,
    )
    def verify_dynamic_memory_lower_limit(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hv_balloon(ctx)
        ctx.hyperv.apply_memory_pressure(memory_mb=2048, duration=45)
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        net_mb_transaction = self._pages_to_mb(ctx, net_pages_transaction)
        expected_delta_mb = (
            ctx.dynamic_memory_config.minimum_mb - ctx.dynamic_memory_config.startup_mb
        )
        assert_that(net_mb_transaction).described_as(
            "net_mb_transaction must equal minimum_memory_mb - startup_memory_mb"
        ).is_equal_to(expected_delta_mb)
        self._validate_host_guest_alignment(ctx)

    @TestCaseMetadata(
        description="""Validate Balloon Down under VM Stress""",
        priority=1,
    )
    def verify_dynamic_memory_balloon_down(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        self._require_hv_balloon(ctx)
        ctx.hyperv.apply_memory_pressure(memory_mb=2048, duration=45)
        net_pages_transaction_before = self._get_net_pages_transaction(ctx)
        self._apply_vm_stress(ctx, num_workers=64, vm_bytes="25G", duration=45)
        net_pages_transaction_after = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction_after).described_as(
            "Net pages did not rebound after host pressure"
        ).is_greater_than(net_pages_transaction_before)
        self._validate_host_guest_alignment(ctx)

    def _get_context(
        self, node: Node, variables: Dict[str, Any]
    ) -> DynamicMemoryTestContext:
        node_context = get_node_context(node)

        if not node_context.host:
            raise SkippedException("Hyper-V host context is required for these tests")
        hyperv = node_context.host.tools[HyperV]
        dynamic_memory_config = hyperv.get_dynamic_memory_config(node_context.vm_name)
        if not dynamic_memory_config.dynamic_memory_enabled:
            raise SkippedException(
                "Dynamic memory is disabled on the Hyper-V host for this VM"
            )

        if not self.check_debugfs_mounted(node):
            raise SkippedException(
                "Debugfs is not mounted; cannot access hv_balloon metrics"
            )

        uname = node.tools[Uname]
        kernel_info = uname.get_linux_information()
        kernel_config_balloon = self._read_kernel_config(
            node,
            kernel_info.kernel_version_raw,
            "CONFIG_HYPERV_BALLOON",
        )
        kernel_config_hotplug = self._read_kernel_config(
            node,
            kernel_info.kernel_version_raw,
            "CONFIG_MEMORY_HOTPLUG",
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
        return DynamicMemoryTestContext(
            node=node,
            vm_name=node_context.vm_name,
            hyperv=hyperv,
            dynamic_memory_config=dynamic_memory_config,
            balloon_ready=balloon_ready,
            hot_add_ready=hot_add_ready,
            page_size_kb=page_size_kb,
        )

    def _read_kernel_config(self, node: Node, kernel_version: str, config: str) -> bool:
        config_path = f"/boot/config-{kernel_version}"
        result = node.execute(
            f"grep -E '^{config}=(y|m)$' {config_path}",
            sudo=True,
            shell=True,
            no_debug_log=True,
            no_info_log=True,
            no_error_log=True,
        )
        return result.exit_code == 0

    def _apply_vm_stress(
        self,
        ctx: DynamicMemoryTestContext,
        num_workers: int,
        vm_bytes: str,
        duration: int,
    ) -> None:
        stress_ng = ctx.node.tools[StressNg]
        stress_ng.install()
        stress_ng.launch_vm_stressor(
            num_workers=num_workers,
            vm_bytes=vm_bytes,
            timeout_in_seconds=duration,
        )

    def _validate_host_guest_alignment(
        self,
        ctx: DynamicMemoryTestContext,
    ) -> None:
        mem_total_from_host_mb = ctx.hyperv.get_memory_assigned_from_host(ctx.vm_name)
        mem_total_from_vm_mb = self._read_meminfo_value(ctx.node, "MemTotal") // 1024
        difference = abs(mem_total_from_host_mb - mem_total_from_vm_mb)
        assert_that(difference).described_as(
            "Memory reported by Hyper-V host differs from guest MemTotal"
        ).is_less_than_or_equal_to(ctx.host_guest_tolerance_mb)

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

        pages_added = int(data.get("pages_added", "0") or 0)
        pages_ballooned = int(data.get("pages_ballooned", "0") or 0)
        return pages_added - pages_ballooned

    def _get_hv_balloon_info(self, node: Node) -> Tuple[List[str], int]:
        raw = self._read_hv_balloon_debugfs(node)
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

        capabilities_raw = data.get("capabilities", "")
        capabilities = capabilities_raw.split() if capabilities_raw else []
        page_size = int(data.get("page_size", "0") or 0)
        page_size_kb = page_size // 1024 if page_size else 0
        return capabilities, page_size_kb

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

    def check_debugfs_mounted(self, node: Node) -> bool:
        result = node.execute(
            "mount | grep -i debugfs",
            sudo=True,
            shell=True,
            no_debug_log=True,
            no_info_log=True,
            no_error_log=True,
        )
        return result.exit_code == 0
