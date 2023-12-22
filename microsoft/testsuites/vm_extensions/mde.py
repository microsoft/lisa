import time
from typing import Any

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
from lisa.tools import MDE, Curl
from lisa.util import LisaException, SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
        Verify MDE installation
        Microsoft Defender for Endpoint(MDE) for Linux includes
        antimalware and endpoint detection and response (EDR) capabilities.

        This test suites validates if MDE can be installed, onboarded
        and detect an EICAR file.

        The test requires the onboarding script to be kept in Azure Storage Account
        and provide the SAS url for downloading under the
        secret variable `onboarding_script_sas_uri`.

        The suite runs the following tests:
        1. Installation test
        2. Onboarding test
        3. Health test
        4. EICAR detection test
    """,
)
class MDETest(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        variables = kwargs["variables"]
        self.onboarding_script_sas_uri = variables.get("onboarding_script_sas_uri", "")
        if not self.onboarding_script_sas_uri:
            raise SkippedException("Onboarding script SAS URI is not provided.")

    @TestCaseMetadata(
        description="""
            Verify MDE installation, onboarding, health and EICAR detection.
        """,
        priority=1,
        requirement=simple_requirement(
            min_core_count=2, min_memory_mb=1024, unsupported_os=[BSD]
        ),
    )
    def verify_mde(self, node: Node, log: Logger, result: TestResult) -> None:
        # Invoking tools first time, intalls the tool.
        try:
            output = node.tools[MDE]._check_exists()
        except LisaException as e:
            log.error(e)
            output = False

        assert_that(output).described_as("Unable to install MDE").is_equal_to(True)

        self.verify_onboard(node, log, result)

        self.verify_health(node, log, result)

        self.verify_eicar_detection(node, log, result)

    def verify_onboard(self, node: Node, log: Logger, result: TestResult) -> None:
        onboarding_result = node.tools[MDE].onboard(self.onboarding_script_sas_uri)

        assert_that(onboarding_result).described_as(
            "Unable to onboard MDE"
        ).is_equal_to(True)

        output = node.tools[MDE].get_result("health --field licensed")

        assert_that(output).described_as("MDE is not licensed").is_equal_to(["true"])

    def verify_health(self, node: Node, log: Logger, result: TestResult) -> None:
        output = node.tools[MDE].get_result("health", json_out=True)

        log.info(output)

        assert_that(output["healthy"]).described_as("MDE is not healthy").is_equal_to(
            True
        )

    def verify_eicar_detection(
        self, node: Node, log: Logger, result: TestResult
    ) -> None:
        log.info("Running EICAR test")

        output = node.tools[MDE].get_result(
            "health --field real_time_protection_enabled"
        )
        if output == ["false"]:
            output = node.tools[MDE].get_result(
                "config real-time-protection --value enabled", sudo=True
            )
            assert_that(" ".join(output)).described_as(
                "Unable to enable RTP for MDE"
            ).is_equal_to("Configuration property updated.")

        current_threat_list = node.tools[MDE].get_result("threat list")
        log.info(current_threat_list)

        node.tools[Curl].fetch(
            arg="-o /tmp/eicar.com.txt",
            execute_arg="",
            url="https://secure.eicar.org/eicar.com.txt",
        )

        time.sleep(5)  # Wait for remediation

        new_threat_list = node.tools[MDE].get_result("threat list")
        log.info(new_threat_list)

        eicar_detect = " ".join(new_threat_list).replace(
            " ".join(current_threat_list), ""
        )

        log.info(eicar_detect)
        assert_that("Name: Virus:DOS/EICAR_Test_File" in eicar_detect).described_as(
            "MDE is not able to detect EICAR file"
        ).is_equal_to(True)
