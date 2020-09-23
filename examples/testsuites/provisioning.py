from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features import StartStop
from lisa.operating_system import Linux
from lisa.testsuite import simple_requirement
from lisa.tools import Cat
from lisa.util.perf_timer import create_timer


@TestSuiteMetadata(
    area="provisioning",
    category="bvt",
    description="""
    This test suite uses to test an environment provisioning correct.
    """,
    tags=["demo"],
)
class Provisioning(TestSuite):
    @TestCaseMetadata(
        description="""
        this test uses to reboot a node, check it can start correctly
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[StartStop], supported_os=[Linux]
        ),
    )
    def reboot(self) -> None:
        node = self.environment.default_node
        hostname_path = "/proc/sys/kernel/hostname"
        cat = node.tools[Cat]
        name_before_restart = cat.run(hostname_path).stdout
        timer = create_timer()
        start_stop = node.features[StartStop]
        self.log.info("node rebooting")
        start_stop.restart()
        self.log.info(f"node rebooted in {timer}")
        name_after_restart = cat.run(hostname_path).stdout
        self.assertEqual(name_before_restart, name_after_restart)
