# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that  # type: ignore

from lisa import Environment, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.testsuite import simple_requirement
from lisa.tools import Lscpu, Ntttcp


@TestSuiteMetadata(
    area="demo",
    category="functional",
    description="""
    this is an example test suite.
    It helps to understand how test cases works on multiple nodes
    """,
    requirement=simple_requirement(min_count=2),
)
class MultipleNodesDemo(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case send and receive data by ntttcp
        """,
        priority=1,
    )
    def os_info(self, environment: Environment) -> None:
        self.log.info(f"node count: {len(environment.nodes)}")

        for node in environment.nodes.list():
            lscpu = node.tools[Lscpu]
            core_count = lscpu.get_core_count()
            self.log.info(f"index: {node.index}, core_count: {core_count}")

    @TestCaseMetadata(
        description="""
        demo how to test network throughput with ntttcp
        """,
        priority=2,
    )
    def perf_network_tcp_ipv4_throughput_ntttcp_synthetic_singleconnection(
        self, environment: Environment
    ) -> None:
        server_node = environment.nodes[0]
        self.log.info(
            f"server: {server_node.internal_address}:{server_node.internal_port}"
        )
        client_node = environment.nodes[1]
        self.log.info(
            f"client: {client_node.internal_address}:{client_node.internal_port}"
        )

        ntttcp_server = server_node.tools[Ntttcp]
        ntttcp_client = client_node.tools[Ntttcp]

        server_process = ntttcp_server.run_async("-P 1 -t 5 -e")
        client_result = ntttcp_client.run(
            f"-s {server_node.internal_address} -P 1 -n 1 -t 5 -W 1"
        )
        server_result = server_process.wait_result(timeout=10)
        self.log.info(
            f"server throughput: "
            f"{ntttcp_server.get_throughput(server_result.stdout)}"
        )
        self.log.info(
            f"client throughput: "
            f"{ntttcp_client.get_throughput(client_result.stdout)}"
        )
        assert_that(
            client_result.exit_code, "client exit code should be 0."
        ).is_equal_to(0)
        assert_that(
            server_result.exit_code, "server exit code should be 0."
        ).is_equal_to(0)
