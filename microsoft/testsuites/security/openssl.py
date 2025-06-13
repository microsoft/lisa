# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.tools import OpenSSL, Nproc
from lisa.operating_system import CBLMariner


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
        self._openssl_golang__sys_crypto_tests_verify(log, node)
        self.openssl_speed_test(log, node)

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

    @TestCaseMetadata(
        description="""
        This test will use Go experimental system crypto tests
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def _openssl_golang__sys_crypto_tests_verify(self, log: Logger, node: Node) -> None:
        """node.os.install_packages(
            ["golang", "glibc-devel", "gcc", "binutils", "kernel-headers"]
        )"""
        self.run_go_crypto_tests(log, node)
        return

    @TestCaseMetadata(
        description="""
        This test installs go dependencies and
        runs the experimental Go system crypto tests.
    """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
        ),
    )
    def run_go_crypto_tests(self, log: Logger, node: Node) -> None:
        """
        This test runs the experimental Go system crypto tests.
        """
        # installs go dependencies for tests
        node.os.install_packages(
            ["golang", "glibc-devel", "gcc", "binutils", "kernel-headers"]
        )
        # cleans up previous go builds
        node.execute(
            "go clean -testcase",
            cwd="/usr/lib/golang/src",
            expected_exit_code=0,
            expected_exit_code_failure_message=("Go clean up failed."),
            shell=True,
        )
        node.execute(
            "go test -short ./crypto/...",
            cwd="/usr/lib/golang/src",
            update_envs={
                "GOEXPERIMENT": "systemcrypto",
            },
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Setting up Go system crypto environment failed."
            ),
        )

        log.info("golang crypto test set up successfully.")

    @TestCaseMetadata(
        description="""
        This test runs OpenSSL speed test this test will
        run performance tests on OpenSSL cryptography tests,
        not only giving us a performance baseline but also
        testing to make sure crypto functions of openssl are working.
        """,
        priority=2,
    )
    def openssl_speed_test(self, log: Logger, node: Node) -> None:
        # Sets up multiple processes to run the OpenSSL speed test
        num_procs = node.tools[Nproc].get_num_procs()
        result = node.execute(
            # command to run OpenSSL speed test for 1 second using multiple processes
            f"openssl speed -seconds 1 -multi {num_procs}",
            expected_exit_code=0,
            expected_exit_code_failure_message=("OpenSSL speed test failed."),
        )
        assert_that(result.stderr).is_empty()
        log.info(f"OpenSSL speed test result: \n{result.stdout}")
        log.info("OpenSSL speed test completed successfully.")
