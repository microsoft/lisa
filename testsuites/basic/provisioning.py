from lisa import LisaTestCase, LisaTestCaseMetadata, LisaTestMetadata
from lisa.features import StartStop
from lisa.testsuite import simple_requirement
from lisa.tools import Dmesg
from lisa.util.perf_timer import create_timer


@LisaTestCaseMetadata(
    area="provisioning",
    category="functional",
    description="""
    This test suite uses to test an environment provisioning correct or not.
    """,
    tags=[],
)
class Provisioning(LisaTestCase):
    @LisaTestMetadata(
        description="""
        this test uses to restart a node, and compare dmesg output.
        the case fails on any panic in kernel
        """,
        priority=0,
        requirement=simple_requirement(supported_features=[StartStop]),
    )
    def restart(self) -> None:
        node = self.environment.default_node
        dmesg = node.tools[Dmesg]

        dmesg.check_kernel_panic()

        timer = create_timer()
        start_stop = node.features[StartStop]
        self.log.info(f"restarting {node.name}")
        start_stop.restart()
        self.log.info(f"node {node.name} rebooted in {timer}, trying connecting")

        dmesg.check_kernel_panic(force_run=True)
