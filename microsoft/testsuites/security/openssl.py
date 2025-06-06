# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import OpenSSL


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
        Verifies basic OpenSSL encryption and decryption behavior by generating
        a random key and IV, encrypting various types of plaintext, and
        decrypting them back to their original form.
        """,
        priority=2,
    )
    def verify_openssl_basic(self, log: Logger, node: Node) -> None:
        """This function tests the basic functionality of
        OpenSSL by calling helper functions"""
        self._openssl_test_encrypt_decrypt(log, node)
        self.openssl_test_sign_verify(log, node)

    def _openssl_test_encrypt_decrypt(self, log: Logger, node: Node) -> None:
        """
        Tests OpenSSL encryption and decryption functionality.
        This function generates a random key and IV, encrypts various types of
        plaintext, and then decrypts them to verify the functionality.
        """

        # Key and IV for encryption and decryption.
        openssl = node.tools[OpenSSL]
        key_hex = openssl.run(
            "rand -hex 32",
            expected_exit_code=0,
        ).stdout.strip()
        iv_hex = openssl.run(
            "rand -hex 16",
            expected_exit_code=0,
        ).stdout.strip()
        # Test with different data types and sizes
        test_data = [
            "cool",  # Short string
            "A" * 1024,  # Longer string
            "Special chars: !@#$%^&*()",  # Special characters
            json.dumps({"resourceId": "test123"}),  # JSON Azure resource data
        ]

        for plaintext in test_data:
            # Encrypt and decrypt the plaintext
            log.debug(f"Output plaintext: {plaintext}")
            encrypted_data = openssl.encrypt(plaintext, key_hex, iv_hex)
            decrypted_data = openssl.decrypt(encrypted_data, key_hex, iv_hex)
            assert_that(plaintext).described_as(
                "Plaintext and decrypted data do not match"
            ).is_equal_to(decrypted_data)

    def openssl_test_sign_verify(self, log: Logger, node: Node) -> None:
        """
        Tests OpenSSL signing and verification functionality.
        This function generates a key pair, signs a message,
        and verifies the signature.
        """
        openssl = node.tools[OpenSSL]
        private_key, public_key = openssl.create_key_pair()

        plaintext = "cool"
        signature = openssl.sign(plaintext, private_key)
        openssl.verify(plaintext, public_key, signature)

        log.debug("Successfully signed and verified a file.")
