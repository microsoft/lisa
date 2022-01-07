# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, Dict, cast

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    notifier,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Sriov, Synthetic
from lisa.schema import NetworkDataPath
from lisa.tools import Lagscope, Sysctl
from lisa.util import dict_to_fields
from microsoft.testsuites.network.common import stop_firewall
from microsoft.testsuites.performance.common import cleanup_process


@TestSuiteMetadata(
    area="network",
    category="performance",
    description="""
    This test suite is to validate linux network performance.
    """,
)
class NetworkPerformace(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test synthetic network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=72,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_latency_synthetic(self, environment: Environment) -> None:
        self.perf_tcp_latency(environment, "perf_tcp_latency_synthetic")

    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test sriov network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=72,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_latency_sriov(self, environment: Environment) -> None:
        self.perf_tcp_latency(environment, "perf_tcp_latency_sriov")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_process(environment, "lagscope")

    def perf_tcp_latency(self, environment: Environment, test_case_name: str) -> None:
        client = cast(RemoteNode, environment.nodes[0])
        server = cast(RemoteNode, environment.nodes[1])
        client_lagscope = client.tools[Lagscope]
        server_lagscope = server.tools[Lagscope]
        for node in [client, server]:
            sysctl = node.tools[Sysctl]
            sysctl.write("net.core.busy_poll", "50")
            sysctl.write("net.core.busy_read", "50")
        stop_firewall(environment)
        server_lagscope.run_as_server(ip=server.internal_address)
        latency_perf_messages = client_lagscope.run_as_client(
            server_ip=server.internal_address
        )
        data_path: str = ""
        assert (
            client.capability.network_interface
            and client.capability.network_interface.data_path
        )
        if isinstance(client.capability.network_interface.data_path, NetworkDataPath):
            data_path = client.capability.network_interface.data_path.value
        information: Dict[str, str] = environment.get_information()
        for latency_perf_message in latency_perf_messages:
            latency_perf_message = dict_to_fields(information, latency_perf_message)
            latency_perf_message.test_case_name = test_case_name
            latency_perf_message.data_path = data_path
            notifier.notify(latency_perf_message)
