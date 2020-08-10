from lisa import CaseMetadata, SuiteMetadata
from lisa.core.testSuite import TestSuite
from lisa.tool import Ntttcp


@SuiteMetadata(
    area="demo",
    category="simple",
    description="""
    This test suite run a script
    """,
    tags=["demo"],
)
class WithScript(TestSuite):
    @CaseMetadata(
        description="""
        this test case run script on test node.
        """,
        priority=1,
    )
    def script(self) -> None:
        node = self.environment.defaultNode
        ntttcp = node.getTool(Ntttcp)
        ntttcp.help()
