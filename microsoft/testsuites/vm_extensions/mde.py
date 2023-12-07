import time
from typing import cast

from assertpy import assert_that
from retry import retry

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD, Posix
from lisa.sut_orchestrator.azure.common import (
    add_tag_for_vm,
    add_user_assign_identity,
    get_managed_service_identity_client,
    get_node_context,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.sut_orchestrator.azure.tools import Azsecd
from lisa.sut_orchestrator.azure.tools import mdatp
from lisa.testsuite import TestResult
from lisa.tools import Cat, Journalctl, Service
from lisa.util import LisaException, UnsupportedDistroException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    MDE Test Suite
    """,
)
class MDE(TestSuite):
    @TestCaseMetadata(
        description="""
            Verify if MDE is healthy
        """,
        priority=1,
        requirement=simple_requirement(
            #supported_features=[AzureExtension], unsupported_os=[BSD]
        ),
    )
    def verify_health(self, node: Node, log: Logger, result: TestResult) -> None:
        output = node.tools[mdatp].get_result('health', json_out=True)

        log.info(output)

        assert_that(output['healthy']).is_equal_to(True)

