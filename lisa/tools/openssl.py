# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import TYPE_CHECKING

from lisa.executable import Tool

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
        return self._run_with_piped_input(
            ciphertext,
            f"enc -d -{algorithm} -K '{hex_key}' -iv '{hex_iv}' -base64 -A",
        )