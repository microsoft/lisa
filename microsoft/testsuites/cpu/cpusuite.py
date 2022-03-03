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
    simple_requirement,
)
from lisa.environment import Environment
from lisa.node import RemoteNode
from lisa.tools import Fio, Iperf3, Kill
from microsoft.testsuites.cpu.common import verify_cpu_hot_plug


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
        priority=3,
    )
    def verify_cpu_offline_storage_workload(self, log: Logger, node: Node) -> None:
        # run fio process asynchronously on the node
        try:
            fio_process = node.tools[Fio].launch_async(
                name="workload",
                filename="fiodata",
                mode="readwrite",
                iodepth=128,
                numjob=10,
                time=300,
                block_size="1M",
                size_gb=1,
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
        priority=3,
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
