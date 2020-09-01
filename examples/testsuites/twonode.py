from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.testsuite import simple_requirement
from lisa.tools import Ntttcp, Uname


@TestSuiteMetadata(
    area="demo",
    category="demo",
    description="""
    this is an example test suite.
    It helps to understand how test cases works on multiple nodes
    """,
    tags=["demo", "twonode"],
    requirement=simple_requirement(min_count=2),
)
class NtttcpDemo(TestSuite):
    @TestCaseMetadata(
        description="""
        this test case send and receive data by ntttcp
        """,
        priority=1,
    )
    def os_info(self) -> None:
        self._log.info(f"node count: {len(self.environment.nodes)}")

        for node in self.environment.nodes.values():
            uname = node.tools[Uname]
            info = uname.get_linux_information()
            self._log.info(
                f"index: {node.index}, "
                f"release: '{info.kernel_release}', version: '{info.kernel_version}', "
                f"hardware: '{info.hardware_platform}', os: '{info.operating_system}'"
            )

    @TestCaseMetadata(
        description="""
        this test case send and receive data by ntttcp
        """,
        priority=1,
    )
    def send_receive(self) -> None:
        self._log.info(f"node count: {len(self.environment.nodes)}")
        server_node = self.environment.nodes[0]
        client_node = self.environment.nodes[1]

        ntttcp_server = server_node.tools[Ntttcp]
        ntttcp_client = client_node.tools[Ntttcp]

        server_process = ntttcp_server.run_async("-P 1 -t 5 -e")
        ntttcp_client.run(f"-s {server_node.internal_address} -P 1 -n 1 -t 5 -W 1")
        server_process.wait_result()
