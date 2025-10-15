# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import random
import time
from typing import cast

from assertpy import assert_that

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
from microsoft.testsuites.cpu.common import (
    CPUState,
    check_runnable,
    get_idle_cpus,
    set_cpu_state_serial,
    set_interrupts_assigned_cpu,
    verify_cpu_hot_plug,
)


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

    @TestCaseMetadata(
        description="""
            This test will check that the added channels to synthetic network
            adapter do not handle interrupts on offline cpu.
            Steps:
            1. Get list of offline CPUs.
            2. Add channels to synthetic network adapter.
            3. Verify that the channels were added to synthetic network adapter.
            4. Verify that the added channels do not handle interrupts on offline cpu.
            """,
        priority=4,
        requirement=simple_requirement(
            min_core_count=16,
        ),
    )
    def verify_cpu_offline_channel_add(self, log: Logger, node: Node) -> None:
        # skip test if kernel doesn't support cpu hotplug
        check_runnable(node)

        # set vmbus channels target cpu into 0 if kernel supports this feature.
        set_interrupts_assigned_cpu(log, node)

        # when kernel doesn't support above feature, we have to rely on current vm's
        # cpu usage. then collect the cpu not in used exclude cpu0.
        idle_cpus = get_idle_cpus(node)
        log.debug(f"idle cpus: {idle_cpus}")

        # save origin current channel
        origin_device_channel = (
            node.tools[Ethtool].get_device_channels_info("eth0", True)
        ).current_channels
        log.debug(f"origin current channels count: {origin_device_channel}")

        # set channel count into 1 to get idle cpus
        if len(idle_cpus) == 0:
            node.tools[Ethtool].change_device_channels_info("eth0", 1)
            idle_cpus = get_idle_cpus(node)
            log.debug(f"idle cpus: {idle_cpus}")
        if len(idle_cpus) == 0:
            raise SkippedException(
                "all of the cpu are associated vmbus channels, "
                "no idle cpu can be used to test hotplug."
            )

        # set idle cpu state offline and change channels
        # current max channel will be cpu_count - len(idle_cpus)
        # check channels of synthetic network adapter align with current setting channel
        try:
            # take idle cpu to offline
            set_cpu_state_serial(log, node, idle_cpus, CPUState.OFFLINE)

            # get vmbus channels of synthetic network adapter. the synthetic network
            # drivers have class id "f8615163-df3e-46c5-913f-f2d2f965ed0e"
            node.tools[Lsvmbus].get_device_channels(force_run=True)
            thread_count = node.tools[Lscpu].get_thread_count()

            # current max channel count need minus count of idle cpus
            max_channel_count = thread_count - len(idle_cpus)

            first_current_device_channel = (
                node.tools[Ethtool].get_device_channels_info("eth0", True)
            ).current_channels
            log.debug(
                f"current channels count: {first_current_device_channel} "
                "after taking idle cpu to offline"
            )

            # if all cpus besides cpu 0 are changed into offline
            # skip change the channel, since current channel is 1
            first_channel_count = random.randint(1, min(max_channel_count, 64))
            if first_current_device_channel > 1:
                while True:
                    if first_channel_count != first_current_device_channel:
                        break
                    first_channel_count = random.randint(1, min(thread_count, 64))
                node.tools[Ethtool].change_device_channels_info(
                    "eth0", first_channel_count
                )
                first_current_device_channel = (
                    node.tools[Ethtool].get_device_channels_info("eth0", True)
                ).current_channels
                log.debug(
                    f"current channels count: {first_current_device_channel} "
                    f"after changing channel into {first_channel_count}"
                )

            # verify that the added channels do not handle interrupts on offline cpu
            lsvmbus_channels = node.tools[Lsvmbus].get_device_channels(force_run=True)
            for channel in lsvmbus_channels:
                # verify synthetic network adapter channels align with expected value
                if channel.class_id == "f8615163-df3e-46c5-913f-f2d2f965ed0e":
                    log.debug(f"Network synthetic channel: {channel}")
                    assert_that(channel.channel_vp_map).is_length(
                        first_current_device_channel
                    )

                # verify that devices do not handle interrupts on offline cpu
                for channel_vp in channel.channel_vp_map:
                    assert_that(channel_vp.target_cpu).is_not_in(idle_cpus)

            # reset idle cpu to online
            set_cpu_state_serial(log, node, idle_cpus, CPUState.ONLINE)

            # reset max and current channel count into original ones
            # by reloading hv_netvsc driver if hv_netvsc can be reload
            # otherwise reboot vm
            if node.tools[KernelConfig].is_built_as_module("CONFIG_HYPERV_NET"):
                node.tools[Modprobe].reload("hv_netvsc")
            else:
                node.tools[Reboot].reboot()

            # change the combined channels count after all cpus online
            second_channel_count = random.randint(1, min(thread_count, 64))
            while True:
                if first_current_device_channel != second_channel_count:
                    break
                second_channel_count = random.randint(1, min(thread_count, 64))
            node.tools[Ethtool].change_device_channels_info(
                "eth0", second_channel_count
            )
            second_current_device_channel = (
                node.tools[Ethtool].get_device_channels_info("eth0", True)
            ).current_channels
            log.debug(
                f"current channels count: {second_current_device_channel} "
                f"after changing channel into {second_channel_count}"
            )

            # verify that the network adapter channels count changed
            # into new channel count
            lsvmbus_channels = node.tools[Lsvmbus].get_device_channels(force_run=True)
            for channel in lsvmbus_channels:
                # verify that channels were added to synthetic network adapter
                if channel.class_id == "f8615163-df3e-46c5-913f-f2d2f965ed0e":
                    log.debug(f"Network synthetic channel: {channel}")
                    assert_that(channel.channel_vp_map).is_length(second_channel_count)
        finally:
            # reset idle cpu to online
            set_cpu_state_serial(log, node, idle_cpus, CPUState.ONLINE)
            # restore channel count into origin value
            current_device_channel = (
                node.tools[Ethtool].get_device_channels_info("eth0", True)
            ).current_channels
            if current_device_channel != origin_device_channel:
                node.tools[Ethtool].change_device_channels_info(
                    "eth0", origin_device_channel
                )
