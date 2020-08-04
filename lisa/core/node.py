from lisa.core.sshConnection import SshConnection
from lisa.util import constants


class Node:
    def __init__(self, isRemote=True, spec=None, isDefault=False):
        self.isDefault: bool = isDefault
        self.isRemote: bool = isRemote
        self.spec = spec
        self.connection = None
        self.publicSshSession = None

    @staticmethod
    def createNode(
        spec=None, node_type=constants.ENVIRONMENT_NODES_REMOTE, isDefault=False
    ):
        if node_type == constants.ENVIRONMENT_NODES_REMOTE:
            isRemote = True
        elif node_type == constants.ENVIRONMENT_NODES_LOCAL:
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
    ):
        self.connection = SshConnection(
            address, port, publicAddress, publicPort, username, password, privateKeyFile
        )

    def connect(self):
        if self.sshSession is None:
            pass
