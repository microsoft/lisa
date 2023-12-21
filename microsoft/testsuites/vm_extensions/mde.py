import time

from typing import Any
from pathlib import PurePath

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD
from lisa.testsuite import TestResult
from lisa.tools import Curl, MDE as mdatp
from lisa.util import LisaException, SkippedException

@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    MDE Test Suite
    """,
)
class MDE(TestSuite):

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        variables = kwargs["variables"]
        self.onboarding_script = variables.get("onboarding_script", "")
        if not self.onboarding_script:
            raise SkippedException("Onboarding script is not provided.")

    @TestCaseMetadata(
        description="""
            Verify MDE installation
        """,
        priority=1,
        requirement=simple_requirement(min_core_count=2,
                                       min_memory_mb=1024,
                                       unsupported_os=[BSD])
    )
    def verify_mde(self, node: Node, log: Logger, result: TestResult) -> None:

        #Invoking tools first time, intalls the tool.
        try:
            output = node.tools[mdatp]._check_exists()
        except LisaException as e:
            log.error(e)
            output = False

        assert_that(output).described_as('Unable to install MDE').is_equal_to(True)

        self.verify_onboard(node, log, result)

        self.verify_health(node, log, result)

        self.verify_eicar_detection(node, log, result)

    def verify_onboard(self, node: Node, log: Logger, result: TestResult) -> None:

        onboarding_result = node.tools[mdatp].onboard(PurePath(self.onboarding_script))

        assert_that(onboarding_result).is_equal_to(True)

        output = node.tools[mdatp].get_result('health --field licensed')

        assert_that(output).is_equal_to(['true'])

    def verify_health(self, node: Node, log: Logger, result: TestResult) -> None:
        output = node.tools[mdatp].get_result('health', json_out=True)

        log.info(output)

        assert_that(output['healthy']).is_equal_to(True)

    def verify_eicar_detection(self, node: Node, log: Logger, result: TestResult) -> None:
        log.info('Running EICAR test')

        output = node.tools[mdatp].get_result('health --field real_time_protection_enabled')
        if output == ['false']:
            output = node.tools[mdatp].get_result('config real-time-protection --value enabled', sudo=True)
            assert_that(' '.join(output)).is_equal_to('Configuration property updated.')

        current_threat_list= node.tools[mdatp].get_result('threat list')
        log.info(current_threat_list)

        node.tools[Curl].fetch(arg="-o /tmp/eicar.com.txt",
                               execute_arg="",
                               url="https://secure.eicar.org/eicar.com.txt")

        time.sleep(5) #Wait for remediation

        new_threat_list = node.tools[mdatp].get_result('threat list')
        log.info(new_threat_list)

        eicar_detect = ' '.join(new_threat_list).replace(' '.join(current_threat_list), '')

        log.info(eicar_detect)
        assert_that('Name: Virus:DOS/EICAR_Test_File' in eicar_detect).is_equal_to(True)


