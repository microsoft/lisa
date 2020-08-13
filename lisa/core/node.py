from __future__ import annotations

import pathlib
import random
from typing import Dict, Optional, Type, TypeVar, Union, cast

from lisa.core.customScript import CustomScriptBuilder
from lisa.core.tool import Tool
from lisa.tool import Echo, Uname
from lisa.util import constants, env
from lisa.util.connectionInfo import ConnectionInfo
from lisa.util.exceptions import LisaException
from lisa.util.executableResult import ExecutableResult
from lisa.util.logger import log
from lisa.util.perf_timer import create_timer
from lisa.util.process import Process
from lisa.util.shell import Shell

T = TypeVar("T")


class Node:
    def __init__(
        self,
        identifier: str,
        is_remote: bool = True,
        spec: Optional[Dict[str, object]] = None,
        is_default: bool = False,
    ) -> None:
        self.is_default = is_default
        self.is_remote = is_remote
        self.spec = spec
        self.name: str = ""

        self.identifier = identifier
        self.shell = Shell()

        self.kernel_release: str = ""
        self.kernel_version: str = ""
        self.hardware_platform: str = ""
        self.operating_system: str = ""

        self._connection_info: Optional[ConnectionInfo] = None
        self._working_path: pathlib.PurePath = pathlib.PurePath()

        self._tools: Dict[str, Tool] = dict()

        self._is_initialized: bool = False
        self._is_linux: bool = True

    @staticmethod
    def create(
        identifier: str,
        spec: Optional[Dict[str, object]] = None,
        node_type: str = constants.ENVIRONMENTS_NODES_REMOTE,
        is_default: bool = False,
    ) -> Node:
        if node_type == constants.ENVIRONMENTS_NODES_REMOTE:
            is_remote = True
        elif node_type == constants.ENVIRONMENTS_NODES_LOCAL:
            is_remote = False
        else:
            raise LisaException(f"unsupported node_type '{node_type}'")
        node = Node(identifier, spec=spec, is_remote=is_remote, is_default=is_default)
        log.debug(
            f"created node '{node_type}', isDefault: {is_default}, "
            f"isRemote: {is_remote}"
        )
        return node

    def set_connection_info(
        self,
        address: str = "",
        port: int = 22,
        publicAddress: str = "",
        publicPort: int = 22,
        username: str = "root",
        password: str = "",
        privateKeyFile: str = "",
    ) -> None:
        if self._connection_info is not None:
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

        self._connection_info = ConnectionInfo(
            publicAddress, publicPort, username, password, privateKeyFile,
        )
        self.shell.set_connection_info(self._connection_info)
        self.internal_address = address
        self.internal_port = port

    def get_tool_path(self, tool: Optional[Tool] = None) -> pathlib.PurePath:
        assert self._working_path
        if tool:
            tool_name = tool.name
            tool_path = self._working_path.joinpath(constants.PATH_TOOL, tool_name)
        else:
            tool_path = self._working_path.joinpath(constants.PATH_TOOL)
        return tool_path

    def get_tool(self, tool_type: Union[Type[T], CustomScriptBuilder]) -> T:
        if tool_type is CustomScriptBuilder:
            raise LisaException("CustomScript should call getScript with instance")
        if isinstance(tool_type, CustomScriptBuilder):
            tool_key = tool_type.name
        else:
            tool_key = tool_type.__name__
        tool = self._tools.get(tool_key)
        if tool is None:
            # the Tool is not installed on current node, try to install it.
            tool_prefix = f"tool[{tool_key}]"
            log.debug(f"{tool_prefix} is initializing")

            if isinstance(tool_type, CustomScriptBuilder):
                tool = tool_type.build(self)
            else:
                cast_tool_type = cast(Type[Tool], tool_type)
                tool = cast_tool_type(self)
                tool.initialize()

            if not tool.is_installed:
                log.debug(f"{tool_prefix} is not installed")
                if tool.can_install:
                    log.debug(f"{tool_prefix} installing")
                    timer = create_timer()
                    is_success = tool.install()
                    log.debug(f"{tool_prefix} installed in {timer}")
                    if not is_success:
                        raise LisaException(f"{tool_prefix} install failed")
                else:
                    raise LisaException(
                        f"{tool_prefix} doesn't support install on "
                        f"Node({self.identifier}), "
                        f"Linux({self.is_linux}), "
                        f"Remote({self.is_remote})"
                    )
            else:
                log.debug(f"{tool_prefix} is installed already")
            self._tools[tool_key] = tool
        return cast(T, tool)

    def execute(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        process = self.executeasync(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result()

    def executeasync(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        self._initialize()
        return self._execute(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )

    @property
    def is_linux(self) -> bool:
        self._initialize()
        return self._is_linux

    def _initialize(self) -> None:
        if not self._is_initialized:
            # prevent loop calls, set _isInitialized to True first
            self._is_initialized = True
            log.debug(f"initializing node {self.name}")
            self.shell.initialize()
            uname = self.get_tool(Uname)
            (
                self.kernel_release,
                self.kernel_version,
                self.hardware_platform,
                self.operating_system,
            ) = uname.get_linux_information(no_error_log=True)
            if (not self.kernel_release) or ("Linux" not in self.operating_system):
                self._is_linux = False
            if self._is_linux:
                log.info(
                    f"initialized Linux node '{self.name}', "
                    f"kernelRelease: {self.kernel_release}, "
                    f"kernelVersion: {self.kernel_version}"
                    f"hardwarePlatform: {self.hardware_platform}"
                )
            else:
                log.info(f"initialized Windows node '{self.name}', ")

            # set working path
            if self.is_remote:
                assert self.shell
                assert self._connection_info

                if self.is_linux:
                    remote_root_path = pathlib.Path("$HOME")
                else:
                    remote_root_path = pathlib.Path("%TEMP%")
                working_path = remote_root_path.joinpath(
                    constants.PATH_REMOTE_ROOT, env.get_run_path()
                ).as_posix()

                # expand environment variables in path
                echo = self.get_tool(Echo)
                result = echo.run(working_path, shell=True)

                # PurePath is more reasonable here, but spurplus doesn't support it.
                if self.is_linux:
                    self._working_path = pathlib.PurePosixPath(result.stdout)
                else:
                    self._working_path = pathlib.PureWindowsPath(result.stdout)
            else:
                self._working_path = pathlib.Path(env.get_run_local_path())
            log.debug(f"working path is: '{self._working_path}'")
            self.shell.mkdir(self._working_path, parents=True, exist_ok=True)

    def _execute(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        cmd_prefix = f"cmd[{str(random.randint(0, 10000))}]"
        process = Process(cmd_prefix, self.shell, self.is_linux)
        process.start(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process

    def close(self) -> None:
        self.shell.close()
