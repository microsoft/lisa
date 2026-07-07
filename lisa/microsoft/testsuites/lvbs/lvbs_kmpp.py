# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa import (
    LisaException,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import CBLMariner
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import simple_requirement
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="lvbs",
    category="functional",
    description="""
    This suite validates KMPP (Key Management and Protection Platform) TA
    functionality on LVBS images. It exercises the full key lifecycle:
    RSA-PSS key generation, ECC trust chain import, PFX import with
    process-based isolation, and OpenSSL provider sign/verify round-trip.
    Runs on LVBS prod and prod-unsigned images (Azure Linux only).
    """,
    owner="prapal",
)
class LvbsKmpp(TestSuite):
    @TestCaseMetadata(
        description="""
        Verify KMPP TA end-to-end key lifecycle on LVBS images.

        This test is applicable only to LVBS images that ship the kmpptest
        tool and OP-TEE support. It is not expected to pass on general-purpose
        Linux distributions.

        Steps:
        1. Generate RSA-PSS key and self-signed cert inside the TA.
        2. Import ECC root certificate into KMPP trust store.
        3. Import ECC intermediate CA certificate.
        4. Import ECC client PFX with process-based isolation.
        5. Load the ECC key via OpenSSL provider and verify sign/verify.
        """,
        priority=1,
        timeout=300,  # these kmpp tests should not take > 5 mins
        requirement=simple_requirement(
            supported_platform_type=[AZURE],
            supported_os=[CBLMariner],
        ),
    )
    def verify_lvbs_kmpp(self, node: Node, log: Logger) -> None:
        # --- Arrange: Verify kmpptest is available ---
        result = node.execute("command -v kmpptest", shell=True)
        if result.exit_code != 0:
            raise SkippedException(
                "kmpptest command is not available on this node. "
                "This test requires an LVBS image with KMPP TA support."
            )

        tz_id_path = node.get_str_path(node.get_pure_path("/tmp/tz.id"))
        ecc_id_path = node.get_str_path(node.get_pure_path("/tmp/ecc.id"))

        try:
            # --- Act & Assert: selfSignPfx (RSA-PSS key gen + self-signed cert) ---
            log.info("Running kmpptest selfSignPfx (RSA-PSS key generation)...")
            # -f0x10000: KMPP_FLAG_RSA_PSS — selects RSA-PSS padding scheme
            result = node.execute(
                f"kmpptest selfSignPfx -enableGdbusRpc -f0x10000 "
                f"rsa_pss_padding {tz_id_path}",
                sudo=True,
            )
            if result.exit_code != 0:
                raise LisaException(
                    f"kmpptest selfSignPfx failed with exit code "
                    f"{result.exit_code}. "
                    f"stdout: {result.stdout}, stderr: {result.stderr}"
                )
            log.info(
                f"selfSignPfx succeeded — RSA-PSS key generated, ID in {tz_id_path}."
            )

            # --- Act & Assert: importTrusted (ECC root + intermediate CA) ---
            trusted_certs = [
                (
                    "root",
                    "/usr/share/kmpp/test_keys/eccplayroot.pem",
                    "ECC root certificate",
                ),
                (
                    "CA",
                    "/usr/share/kmpp/test_keys/eccplayca.pem",
                    "ECC intermediate CA certificate",
                ),
            ]

            for cert_type, pem_path, description in trusted_certs:
                log.info(f"Importing {description}...")
                pem = node.get_str_path(node.get_pure_path(pem_path))
                result = node.execute(
                    f"kmpptest importTrusted -enableGdbusRpc -cpem {pem}",
                    sudo=True,
                )
                if result.exit_code != 0:
                    raise LisaException(
                        f"kmpptest importTrusted ({cert_type}) failed "
                        f"with exit code {result.exit_code}. "
                        f"stdout: {result.stdout}, "
                        f"stderr: {result.stderr}"
                    )
                log.info(f"{description} imported successfully.")

            # --- Act & Assert: importPfx (ECC client PFX) ---
            log.info("Importing ECC client PFX with process-based isolation...")
            ecc_pfx = node.get_str_path(
                node.get_pure_path("/usr/share/kmpp/test_keys/eccplayclient.pfx")
            )
            # -f0x8000: KMPP_FLAG_PROCESS_ISOLATION — restricts key access to the
            # importing process
            result = node.execute(
                f"kmpptest importPfx -f0x8000 -enableGdbusRpc "
                f"-popenssl {ecc_pfx} {ecc_id_path}",
                sudo=True,
            )
            if result.exit_code != 0:
                raise LisaException(
                    f"kmpptest importPfx failed with exit code "
                    f"{result.exit_code}. "
                    f"stdout: {result.stdout}, stderr: {result.stderr}"
                )
            log.info(f"ECC client PFX imported successfully — key ID in {ecc_id_path}.")

            # --- Act & Assert: loadProvider (OpenSSL sign/verify round-trip) ---
            log.info("Loading ECC key via OpenSSL provider (sign/verify)...")
            result = node.execute(
                f"kmpptest loadProvider -enableGdbusRpc {ecc_id_path}",
                sudo=True,
            )
            if result.exit_code != 0:
                raise LisaException(
                    f"kmpptest loadProvider failed with exit code "
                    f"{result.exit_code}. "
                    f"stdout: {result.stdout}, stderr: {result.stderr}"
                )
            log.info(
                "OpenSSL provider sign/verify round-trip succeeded. "
                "KMPP TA fully validated."
            )
        finally:
            # Clean up temp files to avoid stale state on repeated runs
            node.execute(f"rm -f {tz_id_path} {ecc_id_path}", sudo=True)
