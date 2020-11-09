from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.environment import EnvironmentStatus
from lisa.testsuite import simple_requirement
from lisa.tools import Dmesg
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
    @TestCaseMetadata(
        description="""
        this test uses to restart a node, and compare dmesg output.
        the case fails on any panic in kernel
        """,
        priority=0,
        requirement=simple_requirement(environment_status=EnvironmentStatus.Deployed),
    )
    def smoke_test(self) -> None:
        node = self.environment.default_node
        dmesg = node.tools[Dmesg]

        dmesg.check_kernel_errors()

        timer = create_timer()
        self.log.info(f"restarting {node.name}")
        node.reboot()
        self.log.info(f"node {node.name} rebooted in {timer}, trying connecting")

        dmesg.check_kernel_errors(force_run=True)
