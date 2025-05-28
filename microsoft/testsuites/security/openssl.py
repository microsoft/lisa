# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from collections import namedtuple
import json

from assertpy import assert_that
from tempfile import TemporaryDirectory

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner
import lisa.tools
from lisa.tools import Cat, Curl, Echo, fips, openssl, Nproc, Rm
from lisa.util import LisaException, SkippedException, get_matched_str
from lisa.sut_orchestrator.azure.common import METADATA_ENDPOINT

def openssl_test_encrypt_decrypt(log: Logger, node: Node) -> None:
    # Key and IV for encryption and decryption.
    openssl = node.tools[lisa.tools.OpenSSL]
    key_hex = openssl.run("rand -hex 32", expected_exit_code=0).stdout.strip()
    iv_hex = openssl.run("rand -hex 16", expected_exit_code=0).stdout.strip()

    # Encrypt and decrypt some data to make sure it works.
    plaintext = "cool"
    encrypted_data = openssl.encrypt(plaintext, key_hex, iv_hex)
    decrypted_data = openssl.decrypt(encrypted_data, key_hex, iv_hex)
    assert_that(plaintext).is_equal_to(decrypted_data)

    log.debug("Sucessfully encrypted and decrypted a file.")

def is_fips_enabled(node: Node) -> bool:
    # Check if the system is in FIPS mode.
    if not isinstance(node.os, CBLMariner):
        raise LisaException("This function is only applicable for CBL-Mariner OS.")
    
    if node.security.verify_azl_fips_status():
        return True
    return False
    
    
@TestSuiteMetadata(
    area="security",
    category="functional",
    description="""
    Tests the functionality of OpenSSL, including encryption and decryption
    operations. Validates that OpenSSL can successfully encrypt plaintext data
    and decrypt it back to its original form using generated keys and IVs.
    """,
)

class OpenSSL(TestSuite):
    # @staticmethod
    # def ensure_azl3(node: Node) -> None:
    #     // TODO: Assert that
    #     node.os.assert_release("2.0", "3.0")
    #     if node.os.information.release == "2.0":
    #         raise SkippedException("AZL2 is not supported.")

    @TestCaseMetadata(
        description="""
        Tests basic functionality of openssl.
        """,
        priority=2,
    )
    def verify_openssl_basic(self, log: Logger, node: Node) -> None:
        if isinstance(node.os, CBLMariner) and node.os.information.release == "3.0":
            node.os.install_packages(["SymCrypt", "SymCrypt-OpenSSL"])

        openssl_test_encrypt_decrypt(log, node)
        openssl_test_sign_verify(log, node)
        log.debug("OpenSSL basic functionality test passed.")

        if (
            isinstance(node.os, CBLMariner)
            and node.os.information.release == "3.0"
            and not is_fips_enabled(node)
        ):
            node.os.uninstall_packages(["SymCrypt", "SymCrypt-OpenSSL"])
            openssl_test_encrypt_decrypt(log, node)
            openssl_test_sign_verify(log, node)
            log.debug("OpenSSL basic functionality test passed without SymCrypt.")

    @TestCaseMetadata(
        description="""
        This test runs openssl speed, which will excercise much of of the functionality openssl provides.
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
        ),
    )