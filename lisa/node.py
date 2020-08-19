from __future__ import annotations

import pathlib
import random
from collections import UserDict
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypeVar, Union, cast

from lisa.executable import Tools
from lisa.tool import Echo, Uname
from lisa.util import constants, env
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger
from lisa.util.process import ExecutableResult, Process
from lisa.util.shell import ConnectionInfo, LocalShell, Shell, SshShell

T = TypeVar("T")


class Node:
    def __init__(
        self,
        index: int,
        is_remote: bool = True,
        spec: Optional[Dict[str, object]] = None,
        is_default: bool = False,
        id_: str = "",
    ) -> None:
        """
        id_: passed in by platform, uses to associate with resource in platform
        """
        self.is_default = is_default
        self.is_remote = is_remote
        self.spec = spec
        self.name: str = ""
        self.index = index
        self.id = id_

        self.shell: Shell = LocalShell()

        self.kernel_release: str = ""
        self.kernel_version: str = ""
        self.hardware_platform: str = ""
        self.operating_system: str = ""
        self.tools = Tools(self)
        self.working_path: pathlib.PurePath = pathlib.PurePath()

        self._connection_info: Optional[ConnectionInfo] = None
        self._is_initialized: bool = False
        self._is_linux: bool = True
        self._log = get_logger("node", str(self.index))

    @staticmethod
    def create(
        index: int,
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
        node = Node(index, spec=spec, is_remote=is_remote, is_default=is_default)
        node._log.debug(
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
        self.shell = SshShell(self._connection_info)
        self.internal_address = address
        self.internal_port = port

    def execute(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        process = self.execute_async(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result()

    def execute_async(
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
            self._log.debug(f"initializing node {self.name}")
            self.shell.initialize()
            uname = self.tools[Uname]
            (
                self.kernel_release,
                self.kernel_version,
                self.hardware_platform,
                self.operating_system,
            ) = uname.get_linux_information(no_error_log=True)
            if (not self.kernel_release) or ("Linux" not in self.operating_system):
                self._is_linux = False
            if self._is_linux:
                self._log.info(
                    f"initialized Linux node '{self.name}', "
                    f"kernelRelease: {self.kernel_release}, "
                    f"kernelVersion: {self.kernel_version}"
                    f"hardwarePlatform: {self.hardware_platform}"
                )
            else:
                self._log.info(f"initialized Windows node '{self.name}', ")

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
                echo = self.tools[Echo]
                result = echo.run(working_path, shell=True)

                # PurePath is more reasonable here, but spurplus doesn't support it.
                if self.is_linux:
                    self.working_path = pathlib.PurePosixPath(result.stdout)
                else:
                    self.working_path = pathlib.PureWindowsPath(result.stdout)
            else:
                self.working_path = pathlib.Path(env.get_run_local_path())
            self._log.debug(f"working path is: '{self.working_path}'")
            self.shell.mkdir(self.working_path, parents=True, exist_ok=True)

    def _execute(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        cmd_id = str(random.randint(0, 10000))
        process = Process(
            cmd_id, self.shell, parent_logger=self._log, is_linux=self.is_linux
        )
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


if TYPE_CHECKING:
    NodeDict = UserDict[str, Node]
else:
    NodeDict = UserDict


class Nodes(NodeDict):
    def __init__(self) -> None:
        self._default: Optional[Node] = None
        self._list: List[Node] = list()

    @property
    def default(self) -> Node:
        if self._default is None:
            default = None
            for node in self._list:
                if node.is_default:
                    default = node
                    break
            if default is None:
                if len(self._list) == 0:
                    raise LisaException("No node found in current environment")
                else:
                    default = self._list[0]
            self._default = default
        return self._default

    def __getitem__(self, key: Union[int, str]) -> Node:
        found = None
        if not self._list:
            raise LisaException("no node found")

        if isinstance(key, int):
            if len(self._list) > key:
                found = self._list[key]
        else:
            for node in self._list:
                if node.name == key:
                    found = node
                    break
        if not found:
            raise KeyError(f"cannot find node {key}")

        return found

    def __setitem__(self, key: Union[int, str], v: Node) -> None:
        raise NotImplementedError("don't set node directly, call create_by_*")

    def __len__(self) -> int:
        return len(self._list)

    def close(self) -> None:
        for node in self._list:
            node.close()

    def create_by_config(self, config: Dict[str, object]) -> Optional[Node]:
        node_type = cast(str, config.get(constants.TYPE))
        node = None
        if node_type is None:
            raise LisaException("type of node shouldn't be None")
        if node_type in [
            constants.ENVIRONMENTS_NODES_LOCAL,
            constants.ENVIRONMENTS_NODES_REMOTE,
        ]:
            is_default = cast(bool, config.get(constants.IS_DEFAULT, False))
            node = Node.create(
                len(self._list), node_type=node_type, is_default=is_default
            )
            self._list.append(node)
            if node.is_remote:
                fields = [
                    constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS,
                    constants.ENVIRONMENTS_NODES_REMOTE_PORT,
                    constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS,
                    constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_PORT,
                    constants.ENVIRONMENTS_NODES_REMOTE_USERNAME,
                    constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD,
                    constants.ENVIRONMENTS_NODES_REMOTE_PRIVATEKEYFILE,
                ]
                parameters: Dict[str, Any] = dict()
                for key in config:
                    if key in fields:
                        parameters[key] = cast(str, config[key])
                node.set_connection_info(**parameters)
        return node

    def from_spec(
        self,
        spec: Dict[str, object],
        node_type: str = constants.ENVIRONMENTS_NODES_REMOTE,
    ) -> Node:
        is_default = cast(bool, spec.get(constants.IS_DEFAULT, False))
        node = Node.create(
            len(self._list), spec=spec, node_type=node_type, is_default=is_default
        )
        self._list.append(node)
        return node
