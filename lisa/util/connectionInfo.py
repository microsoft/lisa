import os
from typing import Optional


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

        if (self.password is None or self.password == "") and (
            self.privateKeyFile is None or self.privateKeyFile == ""
        ):
            raise Exception(
                "at least one of password and privateKeyFile need to be set"
            )
        elif self.password is not None and self.password != "":
            self.usePassword = True
        else:
            if not os.path.exists(self.privateKeyFile):
                raise FileNotFoundError(self.privateKeyFile)
            self.password = None
            self.usePassword = False

        if self.username is None or self.username == "":
            raise Exception("username must be set")
