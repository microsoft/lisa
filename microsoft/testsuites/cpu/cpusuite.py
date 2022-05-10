# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

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
from lisa.tools import Ethtool, Fio, Iperf3, Kill, Lscpu, Lsvmbus
from lisa.util import SkippedException
from microsoft.testsuites.cpu.common import (
    CPUState,
    check_runnable,
    get_idle_cpus,
    restore_interrupts_assignment,
    set_cpu_state_serial,
    set_interrupts_assigned_cpu,
    verify_cpu_hot_plug,
)


@TestSuiteMetadata(
    area="cpu",
    category="functional",
    description="""
    This test suite is used to run cpu related tests.
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
        ),
    )
    def verify_cpu_offline_storage_workload(self, log: Logger, node: Node) -> None:
        # run fio process asynchronously on the node
        fio_data_size_in_gb = 1
        try:
            image_folder_path = node.find_partition_with_freespace(fio_data_size_in_gb)
            fio_process = node.tools[Fio].launch_async(
                name="workload",
                filename=f"{image_folder_path}/fiodata",
                mode="readwrite",
                iodepth=128,
                numjob=10,
                time=300,
                block_size="1M",
                size_gb=fio_data_size_in_gb,
                group_reporting=False,
                overwrite=True,
                time_based=True,
            )

            # verify cpu hotplug functionality
            verify_cpu_hot_plug(log, node)

            # verify that the fio was running when hotplug was triggered
            assert_that(
                fio_process.is_running(),
                "Storage workload was not running during CPUhotplug",
            ).is_true()
        finally:
            # kill fio process
            node.tools[Kill].by_name("fio")

    @TestCaseMetadata(
        description="""
            This test will check cpu hotplug with network workload.
            The cpu hotplug steps are same as `verify_cpu_hot_plug` test case.
            """,
        priority=4,
        requirement=simple_requirement(
            min_count=2,
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
                "Network workload was not running during CPUhotplug",
            ).is_true()
        finally:
            # kill fio process
            server.tools[Kill].by_name("iperf3")
            client.tools[Kill].by_name("iperf3")

    @TestCaseMetadata(
        description="""
            This test will check that the added channels to synthetic network
            adapter do not handle interrupts on offlined cpu.
            Steps:
            1. Get list of offlined CPUs.
            2. Add channels to synthetic network adapter.
            3. Verify that the channels were added to synthetic network adapter.
            4. Verify that the added channels do not handle interrupts on offlined cpu.
            """,
        priority=4,
    )
    def verify_cpu_offlined_channel_add(self, log: Logger, node: Node) -> None:
        # skip test if kernel doesn't support cpu hotplug
        check_runnable(node)

        # set vmbus channels target cpu into 0 if kernel supports this feature.
        file_path_list = set_interrupts_assigned_cpu(log, node)

        # when kernel doesn't support above feature, we have to rely on current vm's
        # cpu usage. then collect the cpu not in used exclude cpu0.
        idle_cpus = get_idle_cpus(node)
        log.debug(f"idle cpus: {idle_cpus}")
        if len(idle_cpus) == 0:
            raise SkippedException(
                "all of the cpu are associated vmbus channels, "
                "no idle cpu can be used to test hotplug."
            )

        # set cpu state offline and add channels to synthetic network adapter
        try:
            # Take idle cpu to offline
            set_cpu_state_serial(log, node, idle_cpus, CPUState.OFFLINE)

            # add vmbus channels to synthetic network adapter. The synthetic network
            # drivers have class id "f8615163-df3e-46c5-913f-f2d2f965ed0e"
            node.tools[Lsvmbus].get_device_channels(force_run=True)
            cpu_count = node.tools[Lscpu].get_core_count()
            available_cpus = cpu_count - len(idle_cpus) - 1
            node.tools[Ethtool].change_device_channels_info("eth0", available_cpus)

            # verify that the added channels do not handle interrupts on offlined cpu.
            lsvmbus_channels = node.tools[Lsvmbus].get_device_channels(force_run=True)
            for channel in lsvmbus_channels:
                # verify that channels were added to synthetic network adapter
                if channel.class_id == "f8615163-df3e-46c5-913f-f2d2f965ed0e":
                    log.debug(f"Network synethic channel: {channel}")
                    assert_that(channel.channel_vp_map).is_length(available_cpus)

                # verify that devices do not handle interrupts on offlined cpu
                for channel_vp in channel.channel_vp_map:
                    assert_that(channel_vp.target_cpu).is_not_in(idle_cpus)
        finally:
            # reset idle cpu to online
            set_cpu_state_serial(log, node, idle_cpus, CPUState.ONLINE)

            # when kernel doesn't support set vmbus channels target cpu feature, the
            # dict which stores original status is empty, nothing need to be restored.
            restore_interrupts_assignment(file_path_list, node)
