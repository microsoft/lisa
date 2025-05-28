# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lisa.operating_system import Posix

class OpenSSL(Tool):
    @property
    def command(self) -> str:
        return "openssl"

    @property
    def can_install(self) -> bool:
        return True

# Encryption and Decryption using AES
    def encrypt(
        self,
        plaintext: str,
        hex_key: str,
        hex_iv: str,
        algorithm: str = "aes-256-cbc",
    ) -> str:
        """
        Encrypt the plaintext using the specified key and IV, and return the base64 encoded ciphertext.
        """
        return self._run_with_piped_input(
            plaintext,
            f"enc -{algorithm} -K '{hex_key}' -iv '{hex_iv}' -base64 -A",
        )

    def decrypt(
        self,
        ciphertext: str,
        hex_key: str,
        hex_iv: str,
        algorithm: str = "aes-256-cbc",
    ) -> str:
        """_summary_
        This method decrypts the ciphertext using the specified key and IV, and returns the plaintext.
        Decrypt the ciphertext using the specified key and IV, and return the plaintext.
        """
        return self._run_with_piped_input(
            ciphertext,
            f"enc -d -{algorithm} -K '{hex_key}' -iv '{hex_iv}' -base64 -A",
        )

    def _run_with_piped_input(self, piped_input_cmd: str, openssl_cmd: str) -> str:
        cmd = f"printf '%s' '{piped_input_cmd}' | {self.command} {openssl_cmd}"
        return self.node.execute(
            cmd, shell=True, expected_exit_code=0
        ).stdout.strip()

    def _install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages([self])
        return self._check_exists()
