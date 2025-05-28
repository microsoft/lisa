# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa.lisa.util import SkippedException
from lisa.logger import Logger
from lisa.node import Node
from lisa.testcase import TestCaseMetadata
from lisa.testsuite import TestSuite, TestSuiteMetadata
from lisa.operating_systems.cblmariner import CBLMariner
from lisa.tools.fips import Fips
from lisa.tools.openssl import OpenSSL
from lisa.exceptions import LisaException


def openssl_test_encrypt_decrypt(log: Logger, node: Node) -> None:
    # Key and IV for encryption and decryption.
    openssl = node.tools[OpenSSL]
    key_hex = openssl.run("rand -hex 32", expected_exit_code=0).stdout.strip()
    iv_hex = openssl.run("rand -hex 16", expected_exit_code=0).stdout.strip()

    # Test with different data types and sizes
    test_data = [
        "cool",  # Short string
        "A" * 1024,  # Longer string
        "Special chars: !@#$%^&*()",  # Special characters
    ]
    
    for plaintext in test_data:
        log.debug(f"Testing with data length: {len(plaintext)}")
        encrypted_data = openssl.encrypt(plaintext, key_hex, iv_hex)
        decrypted_data = openssl.decrypt(encrypted_data, key_hex, iv_hex)
        assert_that(plaintext).is_equal_to(decrypted_data)

    log.debug("Successfully encrypted and decrypted all test data.")

def is_fips_enabled(node: Node) -> bool:
    """
    Checks if the system is in FIPS mode and
    verifies AZL FIPS status.
    Check if the system is in FIPS mode.
    """
    if not isinstance(node.os, CBLMariner):
        raise LisaException(
            "This function is only applicable for CBL-Mariner OS."
        )
    fips_tool = node.tools[Fips]
    if not fips_tool.is_fips_enabled():
        return False
    # If FIPS is enabled, verify the AZL FIPS status.
    if not getattr(getattr(node.os, "information", None), "is_azl", False):
        raise LisaException(
            "This function is only applicable for AZL systems."
        )
    security = getattr(node, "security", None)
    if security and hasattr(security, "verify_azl_fips_status"):
        if security.verify_azl_fips_status():
            return True
        else:
            return False
    else:
        raise LisaException(
            "Node security attribute or verify_azl_fips_status method not found."
        )


@TestSuiteMetadata(
    area="security",
    category="functional",
    description="""
    Tests the functionality of OpenSSL, including encryption and decryption
    operations. Validates that OpenSSL can successfully encrypt plaintext data
    and decrypt it back to its original form using generated keys and IVs.
    """,
)
class OpenSSLTestSuite(TestSuite):
    """
    Test suite for OpenSSL functionality.
    """

    @TestCaseMetadata(
        description="""
        Tests basic functionality of openssl.
        """,
        priority=2,
    )
    def verify_openssl_basic(self, log: Logger, node: Node) -> None:
        """
        Verifies basic OpenSSL encryption and decryption, with and without SymCrypt.
        """
        if (
            isinstance(node.os, CBLMariner)
            and node.os.information.release == "3.0"
        ):
            node.os.install_packages(["SymCrypt", "SymCrypt-OpenSSL"])

        openssl_test_encrypt_decrypt(log, node)

        if not node.os.information.is_azl:
            raise SkippedException("This test requires Azure Linux.")

        if node.os.information.release not in ["2.0", "3.0"]:
            raise SkippedException(
                f"Unsupported Azure Linux version: {node.os.information.release}. "
                "Supported versions: 2.0, 3.0"
            )

        if (
            isinstance(node.os, CBLMariner)
            and node.os.information.release == "3.0"
            and not is_fips_enabled(node)
        ):
            node.os.uninstall_packages(["SymCrypt", "SymCrypt-OpenSSL"])
            openssl_test_encrypt_decrypt(log, node)
            log.debug(
                "OpenSSL basic functionality test passed without SymCrypt."
            )