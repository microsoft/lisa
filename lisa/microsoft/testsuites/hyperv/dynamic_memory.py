# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

# import time
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.base_tools import Uname
from lisa.node import RemoteNode
from lisa.operating_system import Linux
from lisa.sut_orchestrator import HYPERV
from lisa.sut_orchestrator.hyperv.context import get_node_context
from lisa.testsuite import simple_requirement
from lisa.tools import HvBalloon, StressNg
from lisa.tools.hyperv import DynamicMemoryConfig, HyperV
from lisa.util import SkippedException


@dataclass
class DynamicMemoryTestContext:
    node: Node
    host: RemoteNode
    vm_name: str
    hyperv: HyperV
    dynamic_memory_config: DynamicMemoryConfig
    balloon: HvBalloon
    host_guest_tolerance_mb: int
    balloon_ready: bool
    hot_add_ready: bool
    min_net_pages_transaction: int
    max_net_pages_transaction: int
    page_size_kb: int


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
        x, y, z = self._validate_host_guest_alignment(ctx)

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
        x, y, z = self._validate_host_guest_alignment(ctx)

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
        x, y, z = self._validate_host_guest_alignment(ctx)

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
        x, y, z = self._validate_host_guest_alignment(ctx)

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
        net_pages_transaction = self._get_net_pages_transaction(ctx)
        assert_that(net_pages_transaction_after).described_as(
            "Net pages did not rebound after host pressure"
        ).is_greater_than(net_pages_transaction_before)
        x, y, z = self._validate_host_guest_alignment(ctx)

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

        host_guest_tolerance_mb = int(
            variables.get("dynamic_memory_host_guest_tolerance_mb", 512)
        )
        kernel_config_balloon, kernel_config_hotplug = self._read_kernel_config(node)
        balloon = node.tools[HvBalloon]
        initial_metrics = balloon.get_metrics()
        capabilities = {cap.lower() for cap in initial_metrics.capabilities}
        balloon_ready = (
            dynamic_memory_config.dynamic_memory_enabled
            and kernel_config_balloon
            and "enabled" in capabilities
        )
        hot_add_ready = (
            balloon_ready and kernel_config_hotplug and "hot_add" in capabilities
        )
        initial_net_pages = initial_metrics.net_pages_transaction
        page_size_kb = initial_metrics.page_size // 1024
        return DynamicMemoryTestContext(
            node=node,
            host=node_context.host,
            vm_name=node_context.vm_name,
            hyperv=hyperv,
            dynamic_memory_config=dynamic_memory_config,
            balloon=balloon,
            host_guest_tolerance_mb=host_guest_tolerance_mb,
            balloon_ready=balloon_ready,
            hot_add_ready=hot_add_ready,
            min_net_pages_transaction=initial_net_pages,
            max_net_pages_transaction=initial_net_pages,
            page_size_kb=page_size_kb,
        )

    def _read_kernel_config(self, node: Node) -> Tuple[bool, bool]:
        uname = node.tools[Uname]
        kernel_info = uname.get_linux_information()
        config_path = f"/boot/config-{kernel_info.kernel_version_raw}"

        def _has(symbol: str) -> bool:
            result = node.execute(
                f"grep -E '^{symbol}=(y|m)$' {config_path}",
                sudo=True,
                shell=True,
                no_debug_log=True,
                no_info_log=True,
                no_error_log=True,
            )
            return result.exit_code == 0

        return _has("CONFIG_HYPERV_BALLOON"), _has("CONFIG_MEMORY_HOTPLUG")

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
    ) -> Tuple[int, int, int]:
        mem_total_from_host_mb = ctx.hyperv.get_memory_assigned_from_host(ctx.vm_name)
        mem_total_from_vm_mb = self._read_meminfo_value(ctx.node, "MemTotal") // 1024
        difference = abs(mem_total_from_host_mb - mem_total_from_vm_mb)
        assert_that(difference).described_as(
            "Memory reported by Hyper-V host differs from guest MemTotal"
        ).is_less_than_or_equal_to(ctx.host_guest_tolerance_mb)
        # Aditya Garg: For development/debugging purpose
        return mem_total_from_host_mb, mem_total_from_vm_mb, difference

    def _read_meminfo_value(self, node: Node, key: str) -> int:
        content = node.execute("cat /proc/meminfo", sudo=False).stdout
        for line in content.splitlines():
            if line.startswith(key):
                value = line.split(":", 1)[1].strip().split()[0]
                return int(value)
        return 0

    def _get_net_pages_transaction(self, ctx: DynamicMemoryTestContext) -> int:
        balloon_metrics = ctx.balloon.get_metrics()
        net_pages_transaction = (
            balloon_metrics.pages_added - balloon_metrics.pages_ballooned
        )
        return net_pages_transaction

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
