import socket
from time import sleep

from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.environment import EnvironmentStatus
from lisa.testsuite import simple_requirement
from lisa.util import LisaException, PartialPassedException
from lisa.util.perf_timer import create_timer


@TestSuiteMetadata(
    area="provisioning",
    category="functional",
    description="""
    This test suite uses to test an environment provisioning correct or not.
    """,
    tags=[],
)
class Provisioning(TestSuite):
    TIME_OUT = 300

    @TestCaseMetadata(
        description="""
        This test try to connect to ssh port to check if a node is healthy.
        If ssh connected, the node is healthy enough. And check if it's healthy after
        reboot. Even not eable to reboot, it's partial passed.
        """,
        priority=0,
        requirement=simple_requirement(environment_status=EnvironmentStatus.Deployed),
    )
    def smoke_test(self) -> None:
        node = self.environment.default_node
        timout_timer = create_timer()
        # TODO: may need to support IPv6.
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connected: bool = False
        times: int = 0
        while timout_timer.elapsed(False) < self.TIME_OUT:
            try:
                result = tcp_socket.connect_ex((node.public_address, node.public_port))
                if result == 0:
                    connected = True
                    self.log.info(f"connected to '{node.name}'")
                    break
                else:
                    if times % 10 == 0:
                        self.log.debug(
                            f"SSH connection failed, and retrying... "
                            f"Tried times: {times}, elapsed: {timout_timer}"
                        )
                    sleep(1)
                    times += 1
            finally:
                tcp_socket.close()
        if not connected:
            raise LisaException(
                f"cannot connect SSH to server "
                f"{node.public_address}:{node.public_port}"
            )

        try:
            timer = create_timer()
            self.log.info(f"restarting {node.name}")
            node.reboot()
            self.log.info(f"node {node.name} rebooted in {timer}, trying connecting")
        except Exception as identifier:
            raise PartialPassedException(identifier)
