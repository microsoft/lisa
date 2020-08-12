from __future__ import annotations
from lisa.util.exceptions import LisaException

import pathlib
import random
from typing import Dict, Optional, Type, TypeVar, Union, cast

from lisa.core.customScript import CustomScript, CustomScriptBuilder
from lisa.core.tool import Tool
from lisa.tool import Echo, Uname
from lisa.util import constants, env
from lisa.util.connectionInfo import ConnectionInfo
from lisa.util.executableResult import ExecutableResult
from lisa.util.logger import log
from lisa.util.process import Process
from lisa.util.shell import Shell

T = TypeVar("T")


class Node:
    def __init__(
        self,
        identifier: str,
        isRemote: bool = True,
        spec: Optional[Dict[str, object]] = None,
        isDefault: bool = False,
    ) -> None:
        self.identifier = identifier
        self.name: str = ""
        self.isDefault = isDefault
        self.isRemote = isRemote
        self.spec = spec
        self.connection_info: Optional[ConnectionInfo] = None
        self.workingPath: pathlib.PurePath = pathlib.PurePath()
        self.shell = Shell()

        self._isInitialized: bool = False
        self._isLinux: bool = True

        self.kernelRelease: str = ""
        self.kernelVersion: str = ""
        self.hardwarePlatform: str = ""
        self.os: str = ""

        self.tools: Dict[str, Tool] = dict()
        self.scripts: Dict[str, CustomScript] = dict()

    @staticmethod
    def createNode(
        identifier: str,
        spec: Optional[Dict[str, object]] = None,
        node_type: str = constants.ENVIRONMENTS_NODES_REMOTE,
        isDefault: bool = False,
    ) -> Node:
        if node_type == constants.ENVIRONMENTS_NODES_REMOTE:
            isRemote = True
        elif node_type == constants.ENVIRONMENTS_NODES_LOCAL:
            isRemote = False
        else:
            raise LisaException(f"unsupported node_type '{node_type}'")
        node = Node(identifier, spec=spec, isRemote=isRemote, isDefault=isDefault)
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
            raise LisaException(
                "node is set connection information already, cannot set again"
            )

        if not address and not publicAddress:
            raise LisaException(
                "at least one of address and publicAddress need to be set"
            )
        elif not address:
            address = publicAddress
        elif not publicAddress:
            publicAddress = address

        if not port and not publicPort:
            raise LisaException("at least one of port and publicPort need to be set")
        elif not port:
            port = publicPort
        elif not publicPort:
            publicPort = port

        self.connection_info = ConnectionInfo(
            publicAddress, publicPort, username, password, privateKeyFile,
        )
        self.shell.setConnectionInfo(self.connection_info)
        self.internalAddress = address
        self.internalPort = port

    def getToolPath(self, tool: Optional[Tool] = None) -> pathlib.PurePath:
        assert self.workingPath
        if tool:
            tool_name = tool.name
            tool_path = self.workingPath.joinpath(constants.PATH_TOOL, tool_name)
        else:
            tool_path = self.workingPath.joinpath(constants.PATH_TOOL)
        return tool_path

    def getTool(self, tool_type: Union[Type[T], CustomScriptBuilder]) -> T:
        if tool_type is CustomScriptBuilder:
            raise LisaException("CustomScript should call getScript with instance")
        if isinstance(tool_type, CustomScriptBuilder):
            tool_key = tool_type.name
        else:
            tool_key = tool_type.__name__
        tool = self.tools.get(tool_key)
        if tool is None:
            # the Tool is not installed on current node, try to install it.
            tool_prefix = f"tool '{tool_key}'"
            log.debug(f"{tool_prefix} is initializing")

            if isinstance(tool_type, CustomScriptBuilder):
                tool_key = tool_type.name
                tool = tool_type.build(self)
            else:
                tool_key = tool_type.__name__
                cast_tool_type = cast(Type[Tool], tool_type)
                tool = cast_tool_type(self)

            if not tool.isInstalled:
                log.debug(f"{tool_prefix} is not installed")
                if tool.canInstall:
                    log.debug(f"{tool_prefix} installing")
                    is_success = tool.install()
                    if not is_success:
                        raise LisaException(f"{tool_prefix} install failed")
                else:
                    raise LisaException(
                        f"{tool_prefix} doesn't support install on "
                        f"Node({self.identifier}), "
                        f"Linux({self.isLinux}), "
                        f"Remote({self.isRemote})"
                    )
            else:
                log.debug(f"{tool_prefix} is installed already")
            self.tools[tool_key] = tool
        return cast(T, tool)

    def execute(
        self,
        cmd: str,
        shell: bool = False,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        process = self.executeAsync(
            cmd, shell=shell, noErrorLog=noErrorLog, noInfoLog=noInfoLog, cwd=cwd
        )
        return process.waitResult()

    def executeAsync(
        self,
        cmd: str,
        shell: bool = False,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        self._initialize()
        return self._execute(
            cmd, shell=shell, noErrorLog=noErrorLog, noInfoLog=noInfoLog, cwd=cwd
        )

    @property
    def isLinux(self) -> bool:
        self._initialize()
        return self._isLinux

    def _initialize(self) -> None:
        if not self._isInitialized:
            # prevent loop calls, set _isInitialized to True first
            self._isInitialized = True
            log.debug(f"initializing node {self.name}")
            self.shell.initialize()
            uname = self.getTool(Uname)
            (
                self.kernelRelease,
                self.kernelVersion,
                self.hardwarePlatform,
                self.os,
            ) = uname.getLinuxInformation(noErrorLog=True)
            if (not self.kernelRelease) or ("Linux" not in self.os):
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

            # set working path
            if self.isRemote:
                assert self.shell
                assert self.connection_info

                if self.isLinux:
                    remote_root_path = pathlib.Path("$HOME")
                else:
                    remote_root_path = pathlib.Path("%TEMP%")
                working_path = remote_root_path.joinpath(
                    constants.PATH_REMOTE_ROOT, env.get_run_path()
                ).as_posix()

                # expand environment variables in path
                echo = self.getTool(Echo)
                result = echo.run(working_path, shell=True)

                # PurePath is more reasonable here, but spurplus doesn't support it.
                if self.isLinux:
                    self.workingPath = pathlib.PurePosixPath(result.stdout)
                else:
                    self.workingPath = pathlib.PureWindowsPath(result.stdout)
            else:
                self.workingPath = pathlib.Path(env.get_run_local_path())
            log.debug(f"working path is: '{self.workingPath}'")
            self.shell.mkdir(self.workingPath, parents=True, exist_ok=True)

    def _execute(
        self,
        cmd: str,
        shell: bool = False,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        cmd_prefix = f"cmd[{str(random.randint(0, 10000))}]"
        process = Process(cmd_prefix, self.shell, self.isLinux)
        process.start(
            cmd, shell=shell, noErrorLog=noErrorLog, noInfoLog=noInfoLog, cwd=cwd
        )
        return process

    def close(self) -> None:
        self.shell.close()
