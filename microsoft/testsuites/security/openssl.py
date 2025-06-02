# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json

from assertpy import assert_that
from lisa import (
    Logger,
    LisaException,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.tools.openssl import OpenSSL

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
        Verifies basic OpenSSL encryption and decryption
        """
        _openssl_test_encrypt_decrypt(log, node)
    
    def _openssl_test_encrypt_decrypt(log: Logger, node: Node) -> None:
        """
        Tests OpenSSL encryption and decryption functionality.
        This function generates a random key and IV, encrypts various types of
        """
    
        # Key and IV for encryption and decryption.   
        openssl = node.tools[OpenSSL]
        key_hex = openssl.run("rand -hex 32", expected_exit_code=0).stdout.strip()
        iv_hex = openssl.run("rand -hex 16", expected_exit_code=0).stdout.strip()

        # Test with different data types and sizes
        test_data = [
            "cool",  # Short string
            "A" * 1024,  # Longer string
            "Special chars: !@#$%^&*()",  # Special characters
            json.dumps({"resourceId": "test123"}),  # JSON Azure resource data
        ]
        for plaintext in test_data:
            log.debug(f"Testing with data length: {len(plaintext)}")
            encrypted_data = openssl.encrypt(plaintext, key_hex, iv_hex)
            decrypted_data = openssl.decrypt(encrypted_data, key_hex, iv_hex)
            assert_that(plaintext).is_equal_to(decrypted_data)

        log.debug("Successfully encrypted and decrypted all test data.")
       