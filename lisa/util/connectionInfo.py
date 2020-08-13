from pathlib import Path
from typing import Optional

from lisa.util.exceptions import LisaException


class ConnectionInfo:
    def __init__(
        self,
        address: str = "",
        port: int = 22,
        username: str = "root",
        password: Optional[str] = "",
        privatekey_file: str = "",
    ) -> None:
        self.address = address
        self.port = port
        self.username = username
        self.password = password
        self.privatekey_file = privatekey_file

        if not self.password and not self.privatekey_file:
            raise LisaException(
                "at least one of password and privateKeyFile need to be set"
            )
        elif not self.privatekey_file:
            self._use_password = True
        else:
            if not Path(self.privatekey_file).exists():
                raise FileNotFoundError(self.privatekey_file)
            self.password = None
            self._use_password = False

        if not self.username:
            raise LisaException("username must be set")
