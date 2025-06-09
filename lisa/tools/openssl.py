# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import TYPE_CHECKING

from lisa.executable import Tool

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
            expected_exit_code_failure_message="Failed to encrypt data with OpenSSL.",
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
            expected_exit_code_failure_message="Failed to decrypt data with OpenSSL.",
        )

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
            expected_exit_code_failure_message: Message to display if the command fails with an unexpected exit code

        Returns:
            The stripped stdout from the command

        Raises:
            LisaException: When the command fails
            or returns unexpected exit code
        """
        sanitized_input = shlex.quote(piped_input_cmd)
        cmd = f"printf '%s' {sanitized_input} | {self.command} {openssl_cmd}"
        result = self.node.execute(
            cmd,
            shell=True,
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
