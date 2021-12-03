# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
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
)
from lisa.nic import NicInfo
from lisa.tools import Cat, Iperf3

from .common import (
    cleanup_iperf3,
    initialize_nic_info,
    sriov_vf_connection_test,
    stop_firewall,
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
        priority=3,
        timeout=3000,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                network_interface=features.Sriov(),
            )
        ),
    )
    def verify_stress_sriov_iperf(self, environment: Environment) -> None:
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])
        vm_nics = initialize_nic_info(environment)
        # preparation work before launch iperf3
        stop_firewall(environment)
        client_iperf3_log = "iperfResults.log"
        server_iperf3 = server_node.tools[Iperf3]
        # 1. Start iperf3 on server node.
        server_iperf3.run_as_server()

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
        assert (
            matched_server_nic_info
        ), "not found the server nic has the same subnet of"
        f" {client_nic_info.ip_addr}"
        client_iperf3 = client_node.tools[Iperf3]
        client_iperf3.run_as_client(
            server_ip=matched_server_nic_info.ip_addr,
            log_file=client_iperf3_log,
            seconds=1800,
            client_ip=client_nic_info.ip_addr,
        )
        client_cat = client_node.tools[Cat]
        iperf_log = client_cat.read_from_file(
            client_iperf3_log, sudo=True, force_run=True
        )
        assert_that(iperf_log).described_as(
            f"iperf client run failed on client node, {iperf_log}"
        ).does_not_contain("error")

        # 3. Do VF connection test.
        sriov_vf_connection_test(environment, vm_nics)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_iperf3(environment)
