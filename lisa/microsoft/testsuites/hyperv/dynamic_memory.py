# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

# import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.base_tools import Uname
from lisa.node import RemoteNode
from lisa.operating_system import Linux
from lisa.sut_orchestrator import HYPERV
from lisa.sut_orchestrator.hyperv.context import get_node_context
from lisa.testsuite import simple_requirement
from lisa.tools import HvBalloon, StressNg
from lisa.tools.hv_balloon import HvBalloonStats
from lisa.tools.hyperv import DynamicMemoryConfig, HyperV
from lisa.util import SkippedException

# from lisa.util.perf_timer import create_timer


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
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._suite_context: Optional[DynamicMemoryTestContext] = None

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        if self._suite_context is None:
            node: Node = kwargs["node"]
            variables: Dict[str, Any] = kwargs["variables"]
            self._suite_context = self._build_context(node, variables)

    @TestCaseMetadata(
        description="""Validate hot add of dynamic memory""",
        priority=1,
    )
    def verify_dynamic_memory_hot_add(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        ctx = self._get_context(node, variables)
        log.info("Aditya Garg: Checking hot add capability")
        self._require_hot_add(ctx)
        log.info(f"Aditya Garg: {ctx}")

        log.info("Aditya Garg: Recording initial net pages transaction")
        self._update_initial_net_pages_transaction(ctx)
        log.info(f"Aditya Garg: {ctx}")
        log.info("Aditya Garg: Applying VM stress")
        self._apply_vm_stress(ctx, num_workers=64, vm_bytes="25G", duration=30)
        log.info("Aditya Garg: Evaluating net pages transaction after stress")
        log.info(f"Aditya Garg: {ctx}")
        stressed_metrics = ctx.balloon.get_metrics()
        log.info(f"Aditya Garg: Stressed metrics: {stressed_metrics}")
        net_pages_transaction = (
            stressed_metrics.pages_added - stressed_metrics.pages_ballooned
        )
        log.info(f"Aditya Garg: Net pages after stress: {net_pages_transaction}")
        assert_that(net_pages_transaction).described_as(
            "Hot add did not increase net pages transaction under VM stress"
        ).is_greater_than(max(0, ctx.max_net_pages_transaction))
        log.info("Aditya Garg: Updating net pages transaction values")
        self._update_net_pages_transaction(ctx, net_pages_transaction)
        log.info("Aditya Garg: Validating host-guest memory alignment")
        x, y, z = self._validate_host_guest_alignment(ctx)
        log.info(f"Aditya Garg: Host: {x} MB, Guest: {y} MB, Difference: {z} MB")
        log.info("Aditya Garg: Hot add dynamic memory test completed successfully")

    # @TestCaseMetadata(
    #     description="""Trigger hot add path using anonymous memory stress""",
    #     priority=1,
    # )
    # def verify_dynamic_memory_hot_add(
    #     self, log: Logger, node: Node, variables: Dict[str, Any]
    # ) -> None:
    #     ctx = self._get_context(node, variables)
    #     self._require_hot_add(ctx)

    #     initial_metrics = ctx.balloon.get_metrics()
    #     self._update_net_extents(ctx, initial_metrics)

    #     self._apply_vm_stress(ctx, num_workers=64, vm_bytes="85%", duration=240)

    #     stressed_metrics = self._wait_for_net_pages(
    #         ctx,
    #         predicate=lambda pages: pages > max(0, ctx.max_net_pages_transaction),
    #         timeout=300,
    #     )
    #     self._update_net_extents(ctx, stressed_metrics)

    #     self._validate_host_guest_alignment(
    #         ctx.node,
    #         ctx.hyperv.get_dynamic_memory_status(ctx.vm_name),
    #         ctx.host_guest_tolerance_mb,
    #     )

    # @TestCaseMetadata(
    #     description="""Drive memory demand toward configured maximum""",
    #     priority=1,
    # )
    # def verify_dynamic_memory_upper_limit(
    #     self, log: Logger, node: Node, variables: Dict[str, Any]
    # ) -> None:
    #     ctx = self._get_context(node, variables)
    #     self._require_hot_add(ctx)

    #     baseline_metrics = ctx.balloon.get_metrics()
    #     baseline_net_pages_transaction = baseline_metrics.pages_added - \
    #         baseline_metrics.pages_ballooned
    #     self._update_net_extents(ctx, baseline_net_pages_transaction)

    #     self._apply_vm_stress(ctx, num_workers=64, vm_bytes="95%", duration=240)
    #     stressed_metrics = ctx.balloon.get_metrics()
    #     stressed_net_pages_transaction = stressed_metrics.pages_added - \
    #         stressed_metrics.pages_ballooned
    #     assert_that(stressed_metrics.net_pages_transaction).described_as(
    #     assert_that(stressed_metrics.net_pages_transaction).described_as(
    #         "Net pages did not increase under VM stress"
    #     ).is_greater_than(baseline_net_pages_transaction)
    #     self._update_net_extents(ctx, stressed_net_pages_transaction)

    #     self._validate_host_guest_alignment(
    #         ctx.node,
    #         ctx.hyperv.get_dynamic_memory_status(ctx.vm_name),
    #         ctx.host_guest_tolerance_mb,
    #     )

    # @TestCaseMetadata(
    #     description="""Induce host memory pressure to balloon up guest""",
    #     priority=1,
    # )
    # def verify_dynamic_memory_balloon_up(
    #     self, log: Logger, node: Node, variables: Dict[str, Any]
    # ) -> None:
    #     ctx = self._get_context(node, variables)
    #     self._require_hv_balloon(ctx)

    #     baseline_metrics = ctx.balloon.get_metrics()
    #     self._update_net_extents(ctx, baseline_metrics)

    #     self._apply_host_memory_pressure(ctx, memory_mb=2048, duration=120)

    #     after_host_metrics = ctx.balloon.get_metrics()
    #     self._update_net_extents(ctx, after_host_metrics)

    #     assert_that(after_host_metrics.net_pages_transaction).described_as(
    #         "Net pages did not decrease under host pressure (balloon up)"
    #     ).is_less_than(ctx.max_net_pages_transaction)

    #     self._validate_host_guest_alignment(
    #         ctx.node,
    #         ctx.hyperv.get_dynamic_memory_status(ctx.vm_name),
    #         ctx.host_guest_tolerance_mb,
    #     )

    # @TestCaseMetadata(
    #     description="""Ensure assigned memory respects configured minimum""",
    #     priority=1,
    # )
    # def verify_dynamic_memory_lower_limit(
    #     self, log: Logger, node: Node, variables: Dict[str, Any]
    # ) -> None:
    #     ctx = self._get_context(node, variables)
    #     self._require_hv_balloon(ctx)

    #     baseline_metrics = ctx.balloon.get_metrics()
    #     baseline_net_pages = baseline_metrics.net_pages_transaction
    #     self._update_net_extents(ctx, baseline_metrics)

    #     self._apply_host_memory_pressure(ctx, memory_mb=2048, duration=120)

    #     after_host_metrics = ctx.balloon.get_metrics()
    #     assert_that(after_host_metrics.net_pages_transaction).described_as(
    #         "Net pages did not decrease under host pressure"
    #     ).is_less_than(baseline_net_pages)
    #     self._update_net_extents(ctx, after_host_metrics)

    #     self._validate_host_guest_alignment(
    #         ctx.node,
    #         ctx.hyperv.get_dynamic_memory_status(ctx.vm_name),
    #         ctx.host_guest_tolerance_mb,
    #     )

    # @TestCaseMetadata(
    #     description="""VM stress then release to validate balloon down""",
    #     priority=1,
    # )
    # def verify_dynamic_memory_balloon_down(
    #     self, log: Logger, node: Node, variables: Dict[str, Any]
    # ) -> None:
    #     ctx = self._get_context(node, variables)
    #     self._require_hv_balloon(ctx)

    #     baseline_metrics = ctx.balloon.get_metrics()
    #     self._update_net_extents(ctx, baseline_metrics)

    #     self._apply_host_memory_pressure(ctx, memory_mb=2048, duration=120)
    #     after_host_metrics = ctx.balloon.get_metrics()
    #     self._update_net_extents(ctx, after_host_metrics)

    #     self._apply_vm_stress(ctx, num_workers=64, vm_bytes="85%", duration=240)
    #     after_vm_metrics = ctx.balloon.get_metrics()
    #     self._update_net_extents(ctx, after_vm_metrics)

    #     assert_that(after_vm_metrics.net_pages_transaction).described_as(
    #         "Net pages did not rebound after host pressure"
    #     ).is_greater_than(ctx.min_net_pages_transaction)

    #     self._validate_host_guest_alignment(
    #         ctx.node,
    #         ctx.hyperv.get_dynamic_memory_status(ctx.vm_name),
    #         ctx.host_guest_tolerance_mb,
    #     )

    # def _wait_for_net_pages(
    #     self,
    #     ctx: DynamicMemoryTestContext,
    #     predicate: Callable[[int], bool],
    #     timeout: int,
    #     poll_seconds: int = 15,
    # ) -> HvBalloonStats:
    #     timer = create_timer()
    #     last_metrics: Optional["HvBalloonStats"] = None
    #     while timer.elapsed(False) < timeout:
    #         metrics = ctx.balloon.get_metrics()
    #         last_metrics = metrics
    #         if predicate(metrics.net_pages_transaction):
    #             return metrics
    #         time.sleep(poll_seconds)
    #     if last_metrics:
    #         return last_metrics
    #     raise LisaException("Timed out waiting for hv_balloon net page change")

    def _get_context(
        self, node: Node, variables: Dict[str, Any]
    ) -> DynamicMemoryTestContext:
        if self._suite_context is not None:
            return self._suite_context

        self._suite_context = self._build_context(node, variables)
        return self._suite_context

    def _build_context(
        self, node: Node, variables: Dict[str, Any]
    ) -> DynamicMemoryTestContext:
        node_context = get_node_context(node)
        # if node_context is not None:
        #     self.__log.info(f"Node context: {node_context}")

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

    def _apply_host_memory_pressure(
        self, ctx: DynamicMemoryTestContext, memory_mb: int, duration: int
    ) -> None:
        ps_command = (
            "$p = Start-Process -FilePath './TestLimit64.exe' "
            f"-ArgumentList '-d {memory_mb}' -PassThru; "
            f"Start-Sleep -Seconds {duration}; "
            "if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force }"
        )
        command = f'pwsh -NoLogo -NoProfile -Command "{ps_command}"'
        ctx.host.execute(command, shell=True, sudo=False)

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

    def _update_net_pages_transaction(
        self, ctx: DynamicMemoryTestContext, net_pages_transaction: int
    ) -> None:
        ctx.min_net_pages_transaction = min(
            ctx.min_net_pages_transaction, net_pages_transaction
        )
        ctx.max_net_pages_transaction = max(
            ctx.max_net_pages_transaction, net_pages_transaction
        )

    def _update_initial_net_pages_transaction(
        self, ctx: DynamicMemoryTestContext
    ) -> None:
        balloon_metrics = ctx.balloon.get_metrics()
        net_pages_transaction = (
            balloon_metrics.pages_added - balloon_metrics.pages_ballooned
        )
        ctx.min_net_pages_transaction = min(
            ctx.min_net_pages_transaction,
            net_pages_transaction,
        )
        ctx.max_net_pages_transaction = max(
            ctx.max_net_pages_transaction,
            net_pages_transaction,
        )

    def _pages_to_mb(self, metrics: HvBalloonStats) -> int:
        if metrics.page_size <= 0:
            return 0
        net_pages_transaction = metrics.pages_added - metrics.pages_ballooned
        return (net_pages_transaction * metrics.page_size) // (1024 * 1024)

    def _pages_to_kb(self, metrics: HvBalloonStats) -> int:
        if metrics.page_size <= 0:
            return 0
        net_pages_transaction = metrics.pages_added - metrics.pages_ballooned
        return (net_pages_transaction * metrics.page_size) // 1024

    def _require_hv_balloon(self, ctx: DynamicMemoryTestContext) -> None:
        if not ctx.balloon_ready:
            raise SkippedException("Ballooning prerequisites not satisfied")

    def _require_hot_add(self, ctx: DynamicMemoryTestContext) -> None:
        if not ctx.hot_add_ready:
            raise SkippedException("Hot add prerequisites not satisfied")
