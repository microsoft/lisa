# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from pathlib import Path
from typing import cast

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner
from lisa.tools import OpenSSL


@TestSuiteMetadata(
    area="security",
    category="functional",
    description="""
    Tests the functionality of OpenSSL, including encryption and decryption
    operations. Validates that OpenSSL can successfully encrypt plaintext data
    and decrypt it back to its original form using generated keys and IVs.
    Validates that OpenSSL signs and verifies signatures correctly.
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
        self._openssl_test_sign_verify(log, node)

    @TestCaseMetadata(
        description="""
        This test will use Go experimental system crypto tests
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def verify_openssl_golang_sys_crypto_tests(self, log: Logger, node: Node) -> None:
        """Verifies the Go experimental system crypto tests"""
        self._run_go_crypto_tests(log, node)
        return

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

    def _openssl_test_sign_verify(self, log: Logger, node: Node) -> None:
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

    def _run_go_crypto_tests(self, log: Logger, node: Node) -> None:
        """
        This test sets up the dependencies to run the
        experimental Go system crypto tests and cleans go builds.
        """
        # installs go dependencies for tests
        az_os = cast(CBLMariner, node.os)
        az_os.install_packages(
            ["golang", "glibc-devel", "gcc", "binutils", "kernel-headers"]
        )
        # cleans up previous go builds
        node.execute(
            "go clean -testcache",
            cwd=Path("/usr/lib/golang/src"),
            expected_exit_code=0,
            expected_exit_code_failure_message=("Go clean up failed."),
            shell=True,
        )
        node.execute(
            "go test -short ./crypto/...",
            cwd=Path("/usr/lib/golang/src"),
            update_envs={
                "GOEXPERIMENT": "systemcrypto",
            },
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Setting up Go system crypto environment failed."
            ),
        )

        log.info("golang crypto test set up successfully.")
