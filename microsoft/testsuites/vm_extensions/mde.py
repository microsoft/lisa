import os
import time
import requests

from typing import Any
from pathlib import Path, PurePath

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
from lisa.sut_orchestrator.azure.tools import mdatp
from lisa.testsuite import TestResult
from lisa.tools import  RemoteCopy, Whoami, Curl
from lisa import CustomScriptBuilder, CustomScript
from lisa.util import LisaException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    MDE Test Suite
    """,
)
class MDE(TestSuite):

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        response = requests.get("https://raw.githubusercontent.com/microsoft/mdatp-xplat/master/linux/installation/mde_installer.sh")
        if response.ok:
            script = response.text
            import tempfile
            _, self.mde_installer = tempfile.mkstemp(prefix='mde_installer', suffix='.sh')
            with open(self.mde_installer, 'w') as writer:
                writer.write(script)
            self._echo_script = CustomScriptBuilder(Path(os.path.dirname(self.mde_installer)),
                                                [os.path.basename(self.mde_installer)])
        else:
            log.error('Unable to download mde_installer.sh script')

    @TestCaseMetadata(
        description="""
            Verify MDE installation
        """,
        priority=1,
        requirement=simple_requirement(min_core_count=2,
                                       min_memory_mb=1024,
                                       unsupported_os=[BSD])
    )
    def verify_install(self, node: Node, log: Logger, result: TestResult) -> None:
        script: CustomScript = node.tools[self._echo_script]
        log.info('Installing MDE')
        result1 = script.run(parameters="--install", sudo=True)
        log.info(result1)

        try:
            output = node.tools[mdatp]._check_exists()
        except LisaException as e:
            log.error(e)
            output = False

        assert_that(output).described_as('Unable to install MDE').is_equal_to(True)

    @TestCaseMetadata(
        description="""
            Verify if MDE is healthy
        """,
        priority=1,
        requirement=simple_requirement(min_core_count=2,
                                       min_memory_mb=1024,
                                       unsupported_os=[BSD])
    )
    def verify_onboard(self, node: Node, log: Logger, result: TestResult) -> None:
        username = node.tools[Whoami].get_username()

        remote_copy = node.tools[RemoteCopy]
        remote_copy.copy_to_remote(
            PurePath("/home/zakhter/projects/lab/MicrosoftDefenderATPOnboardingLinuxServer.py"), PurePath(f"/home/{username}/MicrosoftDefenderATPOnboardingLinuxServer.py"))

        script: CustomScript = node.tools[self._echo_script]

        log.info('Onboarding MDE')
        result1 = script.run(parameters=f"--onboard /home/{username}/MicrosoftDefenderATPOnboardingLinuxServer.py/MicrosoftDefenderATPOnboardingLinuxServer.py", sudo=True)
        log.info(result1)

        output = node.tools[mdatp].get_result('health --field licensed')

        log.info(output)

        assert_that(output).is_equal_to(['true'])

    @TestCaseMetadata(
        description="""
            Verify if MDE is healthy
        """,
        priority=1,
        requirement=simple_requirement(min_core_count=2,
                                       min_memory_mb=1024,
                                       unsupported_os=[BSD])
    )
    def verify_health(self, node: Node, log: Logger, result: TestResult) -> None:
        output = node.tools[mdatp].get_result('health', json_out=True)

        log.info(output)

        assert_that(output['healthy']).is_equal_to(True)

    @TestCaseMetadata(
        description="""
            Verify if MDE is healthy
        """,
        priority=1,
        requirement=simple_requirement(min_core_count=2,
                                       min_memory_mb=1024,
                                       unsupported_os=[BSD])
    )
    def eicar_test(self, node: Node, log: Logger, result: TestResult) -> None:
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
        log.info(eicar_detect.find('Name: Virus:DOS/EICAR_Test_File'))
        assert_that('Name: Virus:DOS/EICAR_Test_File' in eicar_detect).is_equal_to(True)


