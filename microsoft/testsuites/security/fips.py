# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="security",
    category="functional",
    description="""
    Tests the functionality of FIPS enable
    """,
)
class Fips(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will
        1. Check whether FIPS can be enabled on the VM
        2. Enable FIPS
        3. Restart the VM for the changes to take effect
        4. Verify that FIPS was enabled properly
        """,
        priority=3,
    )
    def verify_fips_enable(self, log: Logger, node: Node) -> None:
        result = node.execute("command -v fips-mode-setup", shell=True)
        if result.exit_code != 0:
            raise SkippedException(
                "Command not found: fips-mode-setup. "
                f"Please ensure {node.os.name} supports fips mode."
            )

        node.execute("fips-mode-setup --enable", sudo=True)

        log.info("FIPS mode set to enable. Attempting reboot.")
        node.reboot()

        result = node.execute("fips-mode-setup --check")

        assert_that(result.stdout).described_as(
            "FIPS was not properly enabled."
        ).contains("is enabled")
