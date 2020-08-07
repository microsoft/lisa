from typing import Optional
from pathlib import Path


class ConnectionInfo:
    def __init__(
        self,
        address: str = "",
        port: int = 22,
        username: str = "root",
        password: Optional[str] = "",
        privateKeyFile: str = "",
    ) -> None:
        self.address = address
        self.port = port
        self.username = username
        self.password = password
        self.privateKeyFile = privateKeyFile

        if not self.password and not self.privateKeyFile:
            raise Exception(
                "at least one of password and privateKeyFile need to be set"
            )
        elif not self.privateKeyFile:
            self.usePassword = True
        else:
            if not Path(self.privateKeyFile).exists():
                raise FileNotFoundError(self.privateKeyFile)
            self.password = None
            self.usePassword = False

        if not self.username:
            raise Exception("username must be set")
