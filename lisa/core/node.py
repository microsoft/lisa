from __future__ import annotations

from typing import Dict, Optional

from lisa.core.sshConnection import SshConnection
from lisa.util import constants


class Node:
    def __init__(
        self,
        isRemote: bool = True,
        spec: Optional[Dict[str, object]] = None,
        isDefault: bool = False,
    ):
        self.name: Optional[str] = None
        self.isDefault = isDefault
        self.isRemote = isRemote
        self.spec = spec
        self.connection = None
        self.publicSshSession: Optional[SshConnection] = None

    @staticmethod
    def createNode(
        spec: Optional[Dict[str, object]] = None,
        node_type: str = constants.ENVIRONMENTS_NODES_REMOTE,
        isDefault: bool = False,
    ) -> Node:
        if node_type == constants.ENVIRONMENTS_NODES_REMOTE:
            isRemote = True
        elif node_type == constants.ENVIRONMENTS_NODES_LOCAL:
            isRemote = False
        else:
            raise Exception("unsupported node_type '%s'", node_type)
        node = Node(spec=spec, isRemote=isRemote, isDefault=isDefault)
        return node

    def setConnectionInfo(
        self,
        address: str = "",
        port: int = 22,
        publicAddress: str = "",
        publicPort: int = 22,
        username: str = "root",
        password: str = "",
        privateKeyFile: str = "",
    ) -> None:
        self.connection = SshConnection(
            address, port, publicAddress, publicPort, username, password, privateKeyFile
        )

    def connect(self) -> None:
        pass
