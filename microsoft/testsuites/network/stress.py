# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from time import sleep
from typing import Any, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    features,
    node_requirement,
    schema,
    simple_requirement,
)
from lisa.features import StartStop
from lisa.nic import NicInfo
from lisa.sut_orchestrator import AZURE
from lisa.tools import Cat, Iperf3
from microsoft.testsuites.network.common import (
    cleanup_iperf3,
    initialize_nic_info,
    sriov_basic_test,
    sriov_disable_enable,
    sriov_vf_connection_test,
)


@TestSuiteMetadata(
    area="sriov",
    category="stress",
    description="""
    This test suite uses to verify accelerated network functionality under stress.
    """,
)
class Stress(TestSuite):
    @TestCaseMetadata(
        description="""
        This case is to check whether the network connectivity is lost after running
         iperf3 for 30 mins.

        Steps,
        1. Start iperf3 on server node.
        2. Start iperf3 for 30 minutes on client node.
        3. Do VF connection test.
        """,
        priority=4,
        timeout=3000,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                network_interface=features.Sriov(),
            )
        ),
    )
    def stress_sriov_iperf(self, environment: Environment) -> None:
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])
        vm_nics = initialize_nic_info(environment)

        client_iperf3_log = "iperfResults.log"
        server_iperf3 = server_node.tools[Iperf3]
        # 1. Start iperf3 on server node.
        server_iperf3.run_as_server_async()

        # 2. Start iperf3 for 30 minutes on client node.
        client_nic_info_list = [
            x
            for _, x in vm_nics[client_node.name].items()
            if x.ip_addr == client_node.internal_address
        ]
        assert_that(client_nic_info_list).described_as(
            "not found the primary network interface."
        ).is_not_none()
        client_nic_info = client_nic_info_list[0]
        isinstance(client_nic_info, NicInfo)
        matched_server_nic_info: NicInfo
        for _, server_nic_info in vm_nics[server_node.name].items():
            if (
                server_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
                == client_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
            ):
                matched_server_nic_info = server_nic_info
                break
        assert matched_server_nic_info, (
            "not found the server nic has the same subnet of"
            f" {client_nic_info.ip_addr}"
        )
        client_iperf3 = client_node.tools[Iperf3]
        client_iperf3.run_as_client(
            server_ip=matched_server_nic_info.ip_addr,
            log_file=client_iperf3_log,
            run_time_seconds=1800,
            client_ip=client_nic_info.ip_addr,
        )
        client_cat = client_node.tools[Cat]
        iperf_log = client_cat.read(client_iperf3_log, sudo=True, force_run=True)
        assert_that(iperf_log).described_as(
            f"iperf client run failed on client node, {iperf_log}"
        ).does_not_contain("error")

        # 3. Do VF connection test.
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after disable and enable accelerated network in
         network interface through sdk under stress.

        It is a regression test case to check the bug
         https://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-azure/+git/
         bionic/commit/id=16a3c750a78d8, which misses the second hunk of the upstream
         patch https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/
         commit/?id=877b911a5ba0. Details please check https://bugs.launchpad.net/
         ubuntu/+source/linux-azure/+bug/1965618

        Steps,
        1. Do the basic sriov check.
        2. Set enable_accelerated_networking as False to disable sriov.
        3. Set enable_accelerated_networking as True to enable sriov.
        4. Do the basic sriov check.
        5. Do step 2 ~ step 4 for 25 times.
        """,
        priority=3,
        timeout=4500,
        requirement=simple_requirement(
            min_core_count=4,
            network_interface=features.Sriov(),
            supported_platform_type=[AZURE],
        ),
    )
    def stress_sriov_disable_enable(self, environment: Environment) -> None:
        sriov_disable_enable(environment, times=50)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provison with max (8) synthetic nics.

        Steps,
        1. Provision VM with max network interfaces with synthetic network.
        2. Check each nic has an ip address.
        3. Reboot VM from guest.
        4. Check each nic has an ip address.
        5. Repeat step 3 and 4 for 10 times.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
            ),
        ),
    )
    def stress_synthetic_provision_with_max_nics_reboot(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment, is_sriov=False)
        for _ in range(10):
            for node in environment.nodes.list():
                node.reboot()
            initialize_nic_info(environment, is_sriov=False)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provison with max (8) synthetic nics.

        Steps,
        1. Provision VM with max network interfaces with synthetic network.
        2. Check each nic has an ip address.
        3. Reboot VM from API.
        4. Check each nic has an ip address.
        5. Repeat step 3 and 4 for 10 times.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
            ),
        ),
    )
    def stress_synthetic_with_max_nics_reboot_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment, is_sriov=False)
        for _ in range(10):
            for node in environment.nodes.list():
                start_stop = node.features[StartStop]
                start_stop.restart()
            initialize_nic_info(environment, is_sriov=False)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provison with max (8) synthetic nics.

        Steps,
        1. Provision VM with max network interfaces with synthetic network.
        2. Check each nic has an ip address.
        3. Stop and Start VM from API.
        4. Check each nic has an ip address.
        5. Repeat step 3 and 4 for 10 times.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
            ),
        ),
    )
    def stress_synthetic_with_max_nics_stop_start_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment, is_sriov=False)
        for _ in range(10):
            for node in environment.nodes.list():
                start_stop = node.features[StartStop]
                start_stop.stop()
                start_stop.start()
            initialize_nic_info(environment, is_sriov=False)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max (8) sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Reboot VM from guest.
        4. Do the basic sriov testing.
        5. Repeat step 3 and 4 for 10 times.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=features.Sriov(),
        ),
    )
    def stress_sriov_with_max_nics_reboot(self, environment: Environment) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for _ in range(10):
            for node in environment.nodes.list():
                node.reboot()
            initialize_nic_info(environment)
            sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max (8) sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Reboot VM from API.
        4. Do the basic sriov testing.
        5. Repeat step 3 and 4 for 10 times.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=features.Sriov(),
        ),
    )
    def stress_sriov_with_max_nics_reboot_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for _ in range(10):
            for node in environment.nodes.list():
                start_stop = node.features[StartStop]
                start_stop.restart()
            # Add delay to wait for the network interface ready.
            sleep(120)
            initialize_nic_info(environment)
            sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max (8) sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Stop and Start VM from API.
        4. Do the basic sriov testing.
        5. Repeat step 3 and 4 for 10 times.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=features.Sriov(),
        ),
    )
    def stress_sriov_with_max_nics_stop_start_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for _ in range(10):
            for node in environment.nodes.list():
                start_stop = node.features[StartStop]
                start_stop.stop()
                start_stop.start()
            # Add delay to wait for the network interface ready.
            sleep(120)
            initialize_nic_info(environment)
            sriov_basic_test(environment)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_iperf3(environment)
