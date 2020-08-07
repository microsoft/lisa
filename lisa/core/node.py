from __future__ import annotations

import random
from timeit import default_timer as timer
from typing import Dict, Optional

from lisa.core.sshConnection import SshConnection
from lisa.util import constants
from lisa.util.excutableResult import ExecutableResult
from lisa.util.logger import log
from lisa.util.process import Process


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
        self.connection: Optional[SshConnection] = None

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
            raise Exception(f"unsupported node_type '{node_type}'")
        node = Node(spec=spec, isRemote=isRemote, isDefault=isDefault)
        return node

    def setConnectionInfo(
        self,
        address: Optional[object],
        port: Optional[object],
        publicAddress: Optional[object],
        publicPort: Optional[object],
        username: Optional[object],
        password: Optional[object],
        privateKeyFile: Optional[object],
    ) -> None:
        if self.connection is not None:
            raise Exception(
                "node is set connection information already, cannot set again"
            )
        parameters: Dict[str, object] = dict()
        if address is not None:
            parameters["address"] = address
        if port is not None:
            parameters["port"] = port
        if publicAddress is not None:
            parameters["publicAddress"] = publicAddress
        if publicPort is not None:
            parameters["publicPort"] = publicPort
        if username is not None:
            parameters["username"] = username
        if password is not None:
            parameters["password"] = password
        if privateKeyFile is not None:
            parameters["privateKeyFile"] = privateKeyFile
        self.connection = SshConnection(**parameters)

    def execute(self, cmd: str) -> ExecutableResult:
        result: ExecutableResult
        cmd_id = random.randint(0, 10000)
        start_timer = timer()
        log.debug(f"remote({self.isRemote}) cmd[{cmd_id}] {cmd}")
        if self.isRemote:
            # remote
            if self.connection is None:
                raise Exception("remote node has no connection info")
            result = self.connection.execute(cmd)
        else:
            # local
            process = Process()
            with process:
                process.start(cmd)
                result = process.waitResult()
        end_timer = timer()
        log.info(f"cmd[{cmd_id}] executed with {end_timer - start_timer}")
        return result

    def cleanup(self) -> None:
        if self.connection is not None:
            self.connection.cleanup()
