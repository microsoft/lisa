# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import shlex
from typing import TYPE_CHECKING, Optional, Tuple

from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.process import ExecutableResult

if TYPE_CHECKING:
    from lisa.operating_system import Posix


class OpenSSL(Tool):
    """
    OpenSSL tool for encryption and decryption operations.
    """

    @property
    def command(self) -> str:
        return "openssl"

    @property
    def can_install(self) -> bool:
        return True

    def encrypt(
        self,
        plaintext: str,
        hex_key: str,
        hex_iv: str,
        algorithm: str = "aes-256-cbc",
    ) -> str:
        """
        Encrypt the plaintext using the specified key and IV,
        and return the base64 encoded ciphertext.
        """
        return self._run_with_piped_input(
            plaintext,
            f"enc -{algorithm} -K '{hex_key}' -iv '{hex_iv}' -base64 -A",
            expected_exit_code_failure_message=("Failed to encrypt data with OpenSSL."),
        )

    def decrypt(
        self,
        ciphertext: str,
        hex_key: str,
        hex_iv: str,
        algorithm: str = "aes-256-cbc",
    ) -> str:
        """
        This method decrypts the ciphertext using the specified
        key and IV, and returns the plaintext.
        Decrypt the ciphertext using the specified
        key and IV, and return the plaintext.
        """
        return self._run_with_piped_input(
            ciphertext,
            f"enc -d -{algorithm} -K '{hex_key}' -iv '{hex_iv}' -base64 -A",
            expected_exit_code_failure_message=("Failed to decrypt data with OpenSSL."),
        )

    def create_key_pair(self, algorithm: str = "RSA") -> Tuple[str, str]:
        """
        Generate a key pair using the specified algorithm.
        Returns the private key and public key as strings.

        This key generation is for testing generation of keys
        with OpenSSL on the remote.
        """
        private_key_result = self.run(
            f"genpkey -algorithm {algorithm} -outform PEM",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to generate private key with OpenSSL."
            ),
        )
        private_key_pem = private_key_result.stdout.strip()
        public_key = self._run_with_piped_input(
            private_key_pem,
            "pkey -in /dev/stdin -pubout -outform PEM",
            expected_exit_code_failure_message=(
                "Failed to generate public key with OpenSSL."
            ),
        )
        return private_key_pem, public_key

    def sign(
        self,
        data: str,
        private_key: str,
        algorithm: str = "sha256",
    ) -> str:
        """
        Sign the data using the specified private key and algorithm.
        Returns the base64 encoded signature.
        """
        return self._run_with_piped_input(
            data,
            f"dgst -{algorithm} -sign <(echo '{private_key}') | openssl base64 -A",
            expected_exit_code_failure_message="Failed to sign data with OpenSSL.",
        )

    def verify(
        self,
        data: str,
        public_key: str,
        signature_base64: str,
        algorithm: str = "sha256",
    ) -> None:
        """
        Verify the signature of the data using the specified
        public key and algorithm.
        """
        self._run_with_piped_input(
            data,
            f"dgst -{algorithm} -verify <(echo '{public_key}') "
            f"-signature <(echo '{signature_base64}' | "
            "openssl base64 -A -d)",
            expected_exit_code_failure_message=(
                "Failed to verify signature with OpenSSL."
            ),
        )

    def speed(self, sec: Optional[int] = None) -> ExecutableResult:
        """
        Run OpenSSL speed test that measures the performance
        of cryptographic functions."""

        # This breaks out the time input for the speed test
        # so it can be made to be a parameter in the future.
        cmd = "speed"
        if sec is not None:
            cmd = f"{cmd} -seconds {sec}"
        # 1 hour timeout to complete all of the cryptographic operations
        # that OpenSSL speed measures.
        result = self.run(
            cmd,
            timeout=3600,
            expected_exit_code=0,
            expected_exit_code_failure_message=("OpenSSL speed test failed."),
        )

        # Check for errors in the output - OpenSSL speed can return exit code 0
        # even when some cryptographic operations fail, so we need to check
        # stdout for error indicators
        if ":error:" in result.stdout:
            raise LisaException(
                f"OpenSSL speed test failed - errors found in output: {result.stdout}"
            )

        return result

    def _run_with_piped_input(
        self,
        piped_input_cmd: str,
        openssl_cmd: str,
        expected_exit_code: int = 0,
        expected_exit_code_failure_message: str = "",
    ) -> str:
        """
        Execute OpenSSL command with piped input and validate results.

        Args:
            piped_input_cmd: The input string to pipe to OpenSSL
            openssl_cmd: The OpenSSL command to execute
            expected_exit_code: Expected exit code from command (default: 0)
            expected_exit_code_failure_message:
            Message to display if the command fails with an unexpected exit code

        Returns:
            The stripped stdout from the command

        Raises:
            LisaException: When the command fails
            or returns unexpected exit code
        """
        sanitized_input = shlex.quote(piped_input_cmd)
        full_cmd = f"printf %s {sanitized_input} | {self.command} {openssl_cmd}"
        cmd = f"bash -c {shlex.quote(full_cmd)}"
        result = self.node.execute(
            cmd,
            expected_exit_code=expected_exit_code,
            expected_exit_code_failure_message=expected_exit_code_failure_message,
        )
        return result.stdout.strip()

    def _install(self) -> bool:
        """
        Install OpenSSL on the node if
        it is not already installed.
        """
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages([self])
        return self._check_exists()
