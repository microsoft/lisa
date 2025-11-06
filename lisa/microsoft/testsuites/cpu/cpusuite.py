# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import random
import re
import time
from typing import List, Optional, cast

from assertpy import assert_that
from microsoft.testsuites.cpu.common import (
    CPUState,
    check_runnable,
    get_idle_cpus,
    set_cpu_state_serial,
    set_interrupts_assigned_cpu,
    verify_cpu_hot_plug,
)

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.node import RemoteNode
from lisa.tools import (
    Ethtool,
    Fio,
    Iperf3,
    KernelConfig,
    Kill,
    Lscpu,
    Lsvmbus,
    Modprobe,
    Reboot,
)
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="cpu",
    category="functional",
    description="""
    This test suite is used to run cpu related tests, set cpu core 16 as minimal
    requreiemnt, since test case relies on idle cpus to do the testing.
    """,
)
class CPUSuite(TestSuite):
    @TestCaseMetadata(
        description="""
            This test will check cpu hotplug.

            Steps :
            1. skip test case when kernel doesn't support cpu hotplug.
            2. set all vmbus channels target to cpu 0.
             when kernel version >= 5.8 and vmbus version >= 4.1, code supports changing
             vmbus channels target cpu, by setting the cpu number to the file
             /sys/bus/vmbus/devices/<device id>/channels/<channel id>/cpu.
             then all cpus except for cpu 0 are in idle state.
                2.1 save the raw cpu number of each channel for restoring after testing.
                2.2 set all vmbus channel interrupts go into cpu 0.
            3. collect idle cpu which can be used for hotplug.
             if the kernel supports step 2, now in used cpu is 0.
             exclude the in used cpu from all cpu list to get idle cpu set which can be
              offline and online.
             if the kernel doesn't step 2,
              the idle cpu is quite rely on the cpu usage at that time.
            4. skip testing when there is no idle cpu can be set offline and online.
            5. set idle cpu offline then back to online.
            6. restore the cpu vmbus channel target cpu back to the original state.
            """,
        priority=3,
        requirement=simple_requirement(
            min_core_count=32,
        ),
    )
    def verify_cpu_hot_plug(self, log: Logger, node: Node) -> None:
        verify_cpu_hot_plug(log, node)

    @TestCaseMetadata(
        description="""
            This test will check cpu hotplug with storage workload.
            The cpu hotplug steps are same as `verify_cpu_hot_plug` test case.
            """,
        priority=4,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=20),
            ),
            min_core_count=16,
        ),
    )
    def verify_cpu_offline_storage_workload(self, log: Logger, node: Node) -> None:
        # run fio process asynchronously on the node
        fio_data_size_in_gb = 1
        try:
            image_folder_path = node.find_partition_with_freespace(fio_data_size_in_gb)
            # Each CPU takes ~10 seconds to toggle offline-online
            fio_run_time = 300 + (node.tools[Lscpu].get_thread_count() * 10)
            fio_process = node.tools[Fio].launch_async(
                name="workload",
                filename=f"{image_folder_path}/fiodata",
                mode="readwrite",
                iodepth=128,
                numjob=10,
                time=fio_run_time,
                block_size="1M",
                size_gb=fio_data_size_in_gb,
                group_reporting=False,
                overwrite=True,
                time_based=True,
            )

            # Added to find an optional runtime for fio_run_time
            # Remove once test is stable
            hot_plug_start_time = time.time()

            # verify cpu hotplug functionality
            verify_cpu_hot_plug(log, node)

            log.debug(f"CPU Hotplug duration: {time.time() - hot_plug_start_time} s")

            # verify that the fio was running when hotplug was triggered
            assert_that(
                fio_process.is_running(),
                "Storage workload was not running during CPUhotplug",
            ).is_true()
        finally:
            # kill fio process
            node.tools[Kill].by_name("fio", ignore_not_exist=True)

    @TestCaseMetadata(
        description="""
            This test will check cpu hotplug with network workload.
            The cpu hotplug steps are same as `verify_cpu_hot_plug` test case.
            """,
        priority=4,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=16,
        ),
    )
    def verify_cpu_offline_network_workload(
        self, log: Logger, environment: Environment
    ) -> None:
        server = cast(RemoteNode, environment.nodes[0])
        client = cast(RemoteNode, environment.nodes[1])

        try:
            # run iperf3 process asynchronously on the server and client
            server.tools[Iperf3].run_as_server_async()
            client_iperf_process = client.tools[Iperf3].run_as_client_async(
                server.internal_address
            )

            # verify cpu hotplug functionality
            verify_cpu_hot_plug(log, client)

            # verify that the iperf3 was running when hotplug was triggered
            assert_that(
                client_iperf_process.is_running(),
                "Network workload was not running during CPU hotplug",
            ).is_true()
        finally:
            # kill fio process
            server.tools[Kill].by_name("iperf3", ignore_not_exist=True)
            client.tools[Kill].by_name("iperf3", ignore_not_exist=True)

    # ---- CPUSuite helpers ----
    def _clamp_channels(self, val: int) -> int:
        return max(1, min(int(val), 64))

    def _read_max_supported_structured(
        self, node: Node, log: Optional[Logger]
    ) -> Optional[int]:
        try:
            info = node.tools[Ethtool].get_device_channels_info("eth0", True)
            candidates = [
                getattr(info, "max_combined", None),
                getattr(info, "max_channels", None),
                getattr(info, "max_current", None),
            ]

            for c in candidates:
                if isinstance(c, str) and c.isdigit():
                    c = int(c)
                if isinstance(c, int) and c > 1:
                    val = self._clamp_channels(c)
                    if log:
                        log.debug(
                            "Structured max channels found: %d (candidates=%s)",
                            val,
                            candidates,
                        )
                    return val
            return None

        except Exception as e:
            if log:
                log.debug("Structured channels info failed: %s", e)
            return None

    def _read_max_supported_raw(
        self, node: Node, log: Optional[Logger]
    ) -> Optional[int]:
        try:
            r = node.execute("ethtool -l eth0", sudo=True)
            raw = r.stdout.strip()
            if log:
                log.debug("Raw `ethtool -l` output:\n%s", raw)

            block = re.search(r"(?is)pre-?set\s+maximums:?(.*?)(?:current|$)", raw)
            if block:
                m = re.search(r"(?im)^\s*Combined\s*:\s*(\d+)\s*$", block.group(1))
                if m:
                    return self._clamp_channels(int(m.group(1)))

            ms = re.findall(r"(?im)^\s*Combined\s*:\s*(\d+)\s*$", raw)
            if ms:
                return self._clamp_channels(max(int(x) for x in ms))

            ms2 = re.findall(r"(?im)(?:Maximum|Combined maximum)\s*:\s*(\d+)", raw)
            if ms2:
                return self._clamp_channels(max(int(x) for x in ms2))

            return None

        except Exception as e:
            if log:
                log.debug("Raw ethtool -l parse failed: %s", e)
            return None

    def _read_max_supported(self, node: Node) -> int:
        """
        Return conservative device max 'combined' channels for eth0.
        Order: ethtool(max_combined/max_channels) -> lsvmbus(queue count) -> threads.
        Always clamp to [1, 64].
        """
        try:
            info = node.tools[Ethtool].get_device_channels_info("eth0", True)
            candidates = []
            for name in ("max_combined", "max_channels", "max_current"):
                v = getattr(info, name, None)
                if v is not None:
                    try:
                        candidates.append(int(v))
                    except Exception:
                        pass
            cur = getattr(info, "current_channels", None)
            if cur is not None:
                try:
                    candidates.append(int(cur))
                except Exception:
                    pass
            if candidates:
                return max(1, min(max(candidates), 64))
        except Exception:
            pass

        try:
            chans = node.tools[Lsvmbus].get_device_channels(force_run=True)
            for ch in chans:
                if ch.class_id == "f8615163-df3e-46c5-913f-f2d2f965ed0e":  # hv_netvsc
                    return max(1, min(len(ch.channel_vp_map), 64))
        except Exception:
            pass

        threads = node.tools[Lscpu].get_thread_count()
        return max(1, min(int(threads), 64))

    def _read_current(self, node: Node) -> int:
        """
        Read current combined channels.
        """
        info = node.tools[Ethtool].get_device_channels_info("eth0", True)
        cur = getattr(info, "current_channels", 1)
        return max(1, int(cur))

    def _set_channels_with_retry(
        self, log: Logger, node: Node, tgt: int, cur: int, soft_upper: int
    ) -> int:
        """
        Set channels to tgt with a single safe retry if it exceeds device max.
        We clamp to min(device_max, soft_upper) first; if still failing with
        'exceeds maximum', we shrink to device_max and retry once.
        """
        dev_max = self._read_max_supported(node)
        final_tgt = max(1, min(int(tgt), int(soft_upper), int(dev_max)))
        if final_tgt == int(cur):
            return cur

        try:
            node.tools[Ethtool].change_device_channels_info("eth0", final_tgt)
            return final_tgt
        except Exception as e:
            msg = str(e)
            if "exceeds maximum" in msg or "Invalid argument" in msg:
                if final_tgt != dev_max:
                    log.debug(
                        "Retrying with device max due to '%s': tgt=%s -> %s",
                        msg,
                        final_tgt,
                        dev_max,
                    )
                    node.tools[Ethtool].change_device_channels_info("eth0", dev_max)
                    return dev_max
            raise

    def _pick_target_not_eq_current(
        self, current: int, upper: int, lower: int = 1
    ) -> int:
        """
        Pick a safe random target in [lower, upper] different from current.
        Always clamp within the allowed range.
        """

        lower = max(1, int(lower))
        upper = max(lower, int(upper))

        # If current already above limit, bring it back first
        current = min(max(current, lower), upper)

        # Candidates within range but != current
        candidates = [x for x in range(lower, upper + 1) if x != current]
        if not candidates:
            return current

        tgt = random.choice(candidates)
        return min(max(tgt, lower), upper)

    def _verify_no_irq_on_offline(
        self, node: Node, offline: List[int], expect_len: int
    ) -> None:
        """
        Assert NIC channel count and that no IRQ is routed to offline CPUs.
        """
        chans = node.tools[Lsvmbus].get_device_channels(force_run=True)
        for ch in chans:
            if ch.class_id == "f8615163-df3e-46c5-913f-f2d2f965ed0e":
                assert_that(ch.channel_vp_map).is_length(expect_len)
                for vp in ch.channel_vp_map:
                    assert_that(vp.target_cpu).is_not_in(offline)

    @TestCaseMetadata(
        description="""
            Validate that changing netvsc combined channels works while some CPUs
            are offline, and that no IRQ is routed to offline CPUs. Capture the
            baseline NIC capability before any CPU is taken offline to avoid
            misjudging capability from a transient state.
        """,
        priority=4,
        requirement=simple_requirement(min_core_count=16),
    )
    def verify_cpu_offline_channel_add(self, log: Logger, node: Node) -> None:
        """
        Validate that changing netvsc combined channels works when some CPUs are
        offline, and that no IRQ is routed to offline CPUs. The target channel
        count is always clamped to the device capability and current CPU limits.
        """

        # ---------- Pre-checks ----------
        check_runnable(node)
        set_interrupts_assigned_cpu(log, node)

        # Baseline capability with CPUs online
        origin_channels = self._read_current(node)
        dev_max0 = self._read_max_supported(node)
        log.debug(
            "Baseline channels: current=%d, device_max=%d",
            origin_channels,
            dev_max0,
        )
        if dev_max0 <= 1:
            raise SkippedException(
                "Device Combined max <= 1 at baseline; cannot add channels."
            )

        # Find idle CPUs; if none, shrink once to 1 and retry
        idle = get_idle_cpus(node)
        log.debug("Idle CPUs (initial): %s", idle)
        if len(idle) == 0:
            node.tools[Ethtool].change_device_channels_info("eth0", 1)
            idle = get_idle_cpus(node)
            log.debug("Idle CPUs (after shrink to 1): %s", idle)
        if len(idle) == 0:
            raise SkippedException(
                "All CPUs are associated with vmbus channels; no idle CPU available."
            )

        try:
            # ---------- Phase 1: CPUs taken offline ----------
            set_cpu_state_serial(log, node, idle, CPUState.OFFLINE)

            threads1 = node.tools[Lscpu].get_thread_count()
            dev_max1 = self._read_max_supported(node)
            upper1 = max(1, min(threads1 - len(idle), dev_max1, 64))

            cur1 = self._read_current(node)

            # If current exceeds the new upper bound, reduce first
            if cur1 > upper1:
                node.tools[Ethtool].change_device_channels_info("eth0", upper1)
                cur1 = self._read_current(node)
                log.debug("Reduced current channels at phase1: %d", cur1)

            tgt1 = self._pick_target_not_eq_current(cur1, upper1)
            new1 = self._set_channels_with_retry(log, node, tgt1, cur1, upper1)
            log.debug(
                "Phase1 set: cur=%d -> %d (upper=%d, dev_max1=%d)",
                cur1,
                new1,
                upper1,
                dev_max1,
            )

            self._verify_no_irq_on_offline(node, idle, new1)

            # ---------- Phase 2: CPUs back online ----------
            set_cpu_state_serial(log, node, idle, CPUState.ONLINE)
            if node.tools[KernelConfig].is_built_as_module("CONFIG_HYPERV_NET"):
                node.tools[Modprobe].reload("hv_netvsc")
            else:
                node.tools[Reboot].reboot()

            threads2 = node.tools[Lscpu].get_thread_count()
            dev_max2 = self._read_max_supported(node)
            upper2 = max(1, min(threads2, dev_max2, 64))

            cur2 = self._read_current(node)
            if cur2 > upper2:
                node.tools[Ethtool].change_device_channels_info("eth0", upper2)
                cur2 = self._read_current(node)
                log.debug("Reduced current channels at phase2: %d", cur2)

            tgt2 = self._pick_target_not_eq_current(cur2, upper2)
            new2 = self._set_channels_with_retry(log, node, tgt2, cur2, upper2)
            log.debug(
                "Phase2 set: cur=%d -> %d (upper=%d, dev_max2=%d)",
                cur2,
                new2,
                upper2,
                dev_max2,
            )

            self._verify_no_irq_on_offline(node, idle, new2)

        finally:
            # ---------- Cleanup: always restore ----------
            try:
                set_cpu_state_serial(log, node, idle, CPUState.ONLINE)
            except Exception as e:
                log.warning("Failed to bring CPUs online during cleanup: %s", e)

            try:
                # Re-read device cap for a safe restore
                dev_max_final = self._read_max_supported(node)
                safe_origin = max(1, min(int(origin_channels), int(dev_max_final)))
                cur_now = self._read_current(node)
                if cur_now != safe_origin:
                    node.tools[Ethtool].change_device_channels_info("eth0", safe_origin)
                    log.debug("Restored channels to origin value: %d", safe_origin)
            except Exception as e:
                log.warning(
                    "Restore channels failed (target=%d): %s", origin_channels, e
                )
