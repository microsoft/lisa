# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner
from lisa.tools import Cat
from lisa.util import LisaException, SkippedException, get_matched_str


@TestSuiteMetadata(
    area="security",
    category="functional",
    description="""
    Tests the functionality of FIPS enable
    """,
)
class Fips(TestSuite):
    _expected_failure_pattern = re.compile(
        "Error setting digest\r\n.*EVP_DigestInit_ex:disabled for FIPS.*", re.M
    )

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
            # check If It is a non-FIPS image
            if node.execute("rpm -qa | grep dracut-fips", shell=True).exit_code != 0:
                raise SkippedException("Not a fips enabled image.")
            else:
                # FIPS image
                result = node.tools[Cat].run(
                    "/proc/sys/crypto/fips_enabled", sudo=True, force_run=True
                )

                if result.exit_code != 0:
                    raise LisaException(
                        "fips_enabled file is not found in proc file system."
                    )

                if "1" != result.stdout:
                    raise LisaException(
                        "fips is not enabled properly. "
                        f"Please ensure {node.os.name} has fips turned on by default."
                    )

                result = node.execute("openssl md5")
                # md5 should not work If It is a FIPS image
                # Following the output of the above command
                # Error setting digest
                # 131590634539840:error:060800C8:digital envelope routines:EVP_DigestInit_ex:disabled for FIPS:crypto/evp/digest.c:135: # noqa: E501
                if result.exit_code != 0:
                    if get_matched_str(result.stdout, self._expected_failure_pattern):
                        log.info("FIPS is enabled properly.")
                    else:
                        raise LisaException(
                            "md5 alogrithm should not work in FIPS mode."
                        )
                else:
                    raise LisaException(
                        "md5 algorithm should not work in FIPS mode. "
                        f"Please ensure {node.os.name} has fips turned on."
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
