from __future__ import annotations

import random
from timeit import default_timer as timer
from typing import Dict, Optional, Type, TypeVar, cast

from lisa.core.executable import Executable
from lisa.core.sshConnection import SshConnection
from lisa.executable import Echo, Uname
from lisa.util import constants
from lisa.util.excutableResult import ExecutableResult
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
        self.connection: Optional[SshConnection] = None

        self._isInitialized: bool = False
        self._isLinux: bool = True

        self.kernelRelease: str = ""
        self.kernelVersion: str = ""
        self.hardwarePlatform: str = ""

        self.tools: Dict[Type[Executable], Executable] = dict()
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

    def setConnectionInfo(self, **kwargs: str) -> None:
        if self.connection is not None:
            raise Exception(
                "node is set connection information already, cannot set again"
            )
        self.connection = SshConnection(**kwargs)

    def getTool(self, tool_type: Type[T]) -> T:
        tool = cast(T, self.tools.get(tool_type))
        if tool is None:
            raise Exception(f"Tool {tool_type.__name__} is not found on node")
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
        cmd_id = str(random.randint(0, 10000))
        start_timer = timer()
        log.debug(f"cmd[{cmd_id}] remote({self.isRemote}) {cmd}")
        if self.isRemote:
            # remote
            if self.connection is None:
                raise Exception(f"cmd[{cmd_id}] remote node has no connection info")
            result: ExecutableResult = self.connection.execute(cmd, cmd_id=cmd_id)
        else:
            # local
            process = Process()
            with process:
                process.start(cmd, cmd_id=cmd_id, noErrorLog=noErrorLog)
                result = process.waitResult()
        end_timer = timer()
        log.info(f"cmd[{cmd_id}] executed with {end_timer - start_timer:.3f} sec")
        return result

    def cleanup(self) -> None:
        if self.connection is not None:
            self.connection.cleanup()
