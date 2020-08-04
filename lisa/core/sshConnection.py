import os


class SshConnection:
    def __init__(
        self,
        address: str = "",
        port: int = 22,
        publicAddress: str = "",
        publicPort: int = 22,
        username: str = "root",
        password: str = "",
        privateKeyFile: str = "",
    ):
        self.address = address
        self.port = port
        self.publicAddress = publicAddress
        self.publicPort = publicPort
        self.username = username
        self.password = password
        self.privateKeyFile = privateKeyFile

        if (self.address is None or self.address == "") and (
            self.publicAddress is None or self.publicAddress == ""
        ):
            raise Exception("at least one of address and publicAddress need to be set")
        elif self.address is None or self.address == "":
            self.address = self.publicAddress
        elif self.publicAddress is None or self.publicAddress == "":
            self.publicAddress = self.address

        if (self.port is None or self.port <= 0) and (
            self.publicPort is None or self.publicPort <= 0
        ):
            raise Exception("at least one of port and publicPort need to be set")
        elif self.port is None or self.port <= 0:
            self.port = self.publicPort
        elif self.publicPort is None or self.publicPort <= 0:
            self.publicPort = self.port

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
            self.usePassword = False

        if self.username is None or self.username == "":
            raise Exception("username must be set")

    def getInternalConnection(self):
        pass

    def getPublicConnection(self):
        pass
