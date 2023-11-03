# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner
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
        if isinstance(node.os, CBLMariner):
            result = node.execute("sudo cat /proc/sys/crypto/fips_enabled")
            if result.exit_code != 0:
                raise SkippedException(
                    "fips_enabled file is not found in proc file system. "
                    f"Please ensure {node.os.name} supports fips mode."
                )

            if "1" != result.stdout:
                raise SkippedException(
                    "fips is not enabled by default. "
                    f"Please ensure {node.os.name} has fips mode turned on by default."
                )

            result = node.execute("sudo sysctl crypto.fips_enabled")
            if result.exit_code != 0 or "crypto.fips_enabled = 1" != result.stdout:
                raise SkippedException(
                    "fips mode is not enabled"
                    f"Please ensure {node.os.name} supports fips mode."
                )

            result = node.execute("rpm -qa | grep dracut-fips")
            if result.exit_code != 0:
                raise SkippedException(
                    "fips is not enabled by default. "
                    f"Please ensure {node.os.name} has fips mode turned on by default."
                )

            result = node.execute("openssl md5")
            if result.exit_code != 0:
                if result.stdout.split("\n")[0] == "Error setting digest":
                    pass
            else:
                raise SkippedException(
                    "openssl is not operating under fips mode."
                )
        else:
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
