from __future__ import annotations

import random
from timeit import default_timer as timer
from typing import Dict, Optional, Type, TypeVar, cast

import spur
import spurplus

from lisa.core.tool import Tool
from lisa.tool import Echo, Uname
from lisa.util import constants
from lisa.util.connectionInfo import ConnectionInfo
from lisa.util.executableResult import ExecutableResult
from lisa.util.logger import log
from lisa.util.process import Process

T = TypeVar("T")


class Node:
    builtinTools = [Uname, Echo]

    def __init__(
        self,
        isRemote: bool = True,
        spec: Optional[Dict[str, object]] = None,
        isDefault: bool = False,
    ) -> None:
        self.name: Optional[str] = None
        self.isDefault = isDefault
        self.isRemote = isRemote
        self.spec = spec
        self.connection_info: Optional[ConnectionInfo] = None
        self.tempFolder: str = ""
        if self.isRemote:
            self.shell: Optional[spurplus.SshShell] = None
        else:
            self.shell: Optional[spur.LocalShell] = None

        self._isInitialized: bool = False
        self._isLinux: bool = True

        self.kernelRelease: str = ""
        self.kernelVersion: str = ""
        self.hardwarePlatform: str = ""

        self.tools: Dict[Type[Tool], Tool] = dict()
        for tool_class in self.builtinTools:
            self.tools[tool_class] = tool_class(self)

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
        log.debug(
            f"created node '{node_type}', isDefault: {isDefault}, isRemote: {isRemote}"
        )
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
        if self.connection_info is not None:
            raise Exception(
                "node is set connection information already, cannot set again"
            )

        if not address and not publicAddress:
            raise Exception("at least one of address and publicAddress need to be set")
        elif not address:
            address = publicAddress
        elif not publicAddress:
            publicAddress = address

        if not port and not publicPort:
            raise Exception("at least one of port and publicPort need to be set")
        elif not port:
            port = publicPort
        elif not publicPort:
            publicPort = port

        self.connection_info = ConnectionInfo(
            publicAddress, publicPort, username, password, privateKeyFile,
        )
        self.internalAddress = address
        self.internalPort = port

    def getTool(self, tool_type: Type[T]) -> T:
        tool = cast(T, self.tools.get(tool_type))
        if tool is None:
            # the Tool is not installed on current node, try to install it.
            tool = cast(Tool, T(self))
            if not tool.isInstalled:
                if tool.canInstall:
                    tool.install()
            if not tool.isInstalled:
                raise Exception(
                    f"Tool {tool_type.__name__} is not found on node, "
                    f"and cannot be installed or is install failed."
                )
        return tool

    def execute(self, cmd: str, noErrorLog: bool = False) -> ExecutableResult:
        self._initialize()
        return self._execute(cmd, noErrorLog)

    @property
    def isLinux(self) -> bool:
        self._initialize()
        return self._isLinux

    def _initialize(self) -> None:
        if not self._isInitialized:
            # prevent loop calls, put it at top
            self._isInitialized = True
            log.debug(f"initializing node {self.name}")
            uname = self.getTool(Uname)

            (
                self.kernelRelease,
                self.kernelVersion,
                self.hardwarePlatform,
            ) = uname.getLinuxInformation(noErrorLog=True)
            if not self.kernelRelease:
                self._isLinux = False
            if self._isLinux:
                log.info(
                    f"initialized Linux node '{self.name}', "
                    f"kernelRelease: {self.kernelRelease}, "
                    f"kernelVersion: {self.kernelVersion}"
                    f"hardwarePlatform: {self.hardwarePlatform}"
                )
            else:
                log.info(f"initialized Windows node '{self.name}', ")

    def _execute(self, cmd: str, noErrorLog: bool = False) -> ExecutableResult:
        cmd_prefix = f"cmd[{str(random.randint(0, 10000))}]"
        start_timer = timer()
        log.debug(f"{cmd_prefix}remote({self.isRemote}) '{cmd}'")

        if self.shell is None:
            if self.isRemote:
                assert self.connection_info is not None
                self.shell = spurplus.connect_with_retries(
                    self.connection_info.address,
                    port=self.connection_info.port,
                    username=self.connection_info.username,
                    password=self.connection_info.password,
                    private_key_file=self.connection_info.privateKeyFile,
                    missing_host_key=spur.ssh.MissingHostKey.accept,
                )
            else:
                self.shell = spur.LocalShell()

        process = Process(cmd_prefix, self.shell)
        process.start(cmd, noErrorLog=noErrorLog)
        result = process.waitResult()

        end_timer = timer()
        log.info(f"{cmd_prefix}executed with {end_timer - start_timer:.3f} sec")
        return result

    def close(self) -> None:
        if self.shell and isinstance(self.shell, spurplus.SshShell):
            self.shell.close()
