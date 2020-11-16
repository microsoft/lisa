from __future__ import annotations

import pathlib
import random
from typing import Any, Callable, Dict, Iterable, List, Optional, TypeVar, Union, cast

from lisa import schema
from lisa.executable import Tools
from lisa.feature import Features
from lisa.operating_system import OperatingSystem
from lisa.tools import Echo, Reboot, Uname
from lisa.util import (
    ContextMixin,
    InitializableMixin,
    LisaException,
    constants,
    fields_to_dict,
)
from lisa.util.logger import get_logger
from lisa.util.process import ExecutableResult, Process
from lisa.util.shell import ConnectionInfo, LocalShell, Shell, SshShell

T = TypeVar("T")


def _get_node_information(node: Node, information: Dict[str, str]) -> None:
    if node.is_connected and node.is_linux:
        uname = node.tools[Uname]
        linux_information = uname.get_linux_information()
        fields = ["hardware_platform", "kernel_version"]
        information_dict = fields_to_dict(linux_information, fields=fields)
        information.update(information_dict)
        information["vm_generation"] = "1"
        cmd_result = node.execute(cmd="ls -lt /sys/firmware/efi", no_error_log=True)
        if cmd_result.exit_code == 0:
            information["vm_generation"] = "2"


class Node(ContextMixin, InitializableMixin):
    def __init__(
        self,
        index: int,
        capability: schema.NodeSpace,
        is_remote: bool = True,
        is_default: bool = False,
        logger_name: str = "node",
    ) -> None:
        super().__init__()
        self.is_default = is_default
        self.is_remote = is_remote
        self.capability = capability
        self.name: str = ""
        self.index = index
        self.is_connected: bool = False

        self.shell: Shell = LocalShell()

        # will be initialized by platform
        self.features: Features
        self.tools = Tools(self)
        self.working_path: pathlib.PurePath = pathlib.PurePath()
        self.log = get_logger(logger_name, str(self.index))

        self._connection_info: Optional[ConnectionInfo] = None
        self._node_information_hooks: List[Callable[[Node, Dict[str, str]], None]] = []
        self.add_node_information_hook(_get_node_information)

    @staticmethod
    def create(
        index: int,
        capability: schema.NodeSpace,
        node_type: str = constants.ENVIRONMENTS_NODES_REMOTE,
        is_default: bool = False,
        logger_name: str = "node",
    ) -> Node:
        if node_type == constants.ENVIRONMENTS_NODES_REMOTE:
            is_remote = True
        elif node_type == constants.ENVIRONMENTS_NODES_LOCAL:
            is_remote = False
        else:
            raise LisaException(f"unsupported node_type '{node_type}'")
        node = Node(
            index,
            capability=capability,
            is_remote=is_remote,
            is_default=is_default,
            logger_name=logger_name,
        )
        node.log.debug(f"created, type: '{node_type}', isDefault: {is_default}")
        return node

    def set_connection_info(
        self,
        address: str = "",
        port: int = 22,
        public_address: str = "",
        public_port: int = 22,
        username: str = "root",
        password: str = "",
        private_key_file: str = "",
    ) -> None:
        if self._connection_info is not None:
            raise LisaException(
                "node is set connection information already, cannot set again"
            )

        self._connection_info = ConnectionInfo(
            public_address,
            public_port,
            username,
            password,
            private_key_file,
        )
        self.shell = SshShell(self._connection_info)
        self.public_address = public_address
        self.public_port = public_port
        self.internal_address = address
        self.internal_port = port

    def reboot(self) -> None:
        self.tools[Reboot].reboot()

    def execute(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
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
        no_info_log: bool = True,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        self.initialize()
        return self._execute(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )

    @property
    def is_linux(self) -> bool:
        self.initialize()
        return self.os.is_linux

    def close(self) -> None:
        self.log.debug("closing node connection...")
        self.shell.close()

    def get_node_information(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for hook in self._node_information_hooks:
            try:
                hook(self, result)
            except Exception as identifier:
                # the message hook shouldn't produce any error
                # they are called on any place, and may bring uncaught exception
                self.log.debug(f"fail on get node information: {identifier}")
        return result

    def add_node_information_hook(
        self, callback: Callable[[Node, Dict[str, str]], None]
    ) -> None:
        self._node_information_hooks.append(callback)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if self.is_remote:
            assert (
                self._connection_info
            ), "call setConnectionInfo before use remote node"
            address = f"{self._connection_info.address}:{self._connection_info.port}"
        else:
            address = "localhost"
        self.log.info(f"initializing node '{self.name}' {address}")
        self.shell.initialize()
        self.os: OperatingSystem = OperatingSystem.create(self)

        # set working path
        if self.is_remote:
            assert self.shell

            if self.is_linux:
                remote_root_path = pathlib.Path("$HOME")
            else:
                remote_root_path = pathlib.Path("%TEMP%")
            working_path = remote_root_path.joinpath(
                constants.PATH_REMOTE_ROOT, constants.RUN_LOGIC_PATH
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
            self.working_path = constants.RUN_LOCAL_PATH
        self.shell.mkdir(self.working_path, parents=True, exist_ok=True)
        self.log.debug(f"working path is: '{self.working_path}'")
        self.is_connected = True

    def _execute(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        cmd_id = str(random.randint(0, 10000))
        process = Process(cmd_id, self.shell, parent_logger=self.log)
        process.start(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process


class Nodes:
    def __init__(self) -> None:
        super().__init__()
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

    def list(self) -> Iterable[Node]:
        for node in self._list:
            yield node

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
        raise NotImplementedError("don't set node directly, call from_*")

    def __len__(self) -> int:
        return len(self._list)

    def initialize(self) -> None:
        for node in self._list:
            node.initialize()

    def close(self) -> None:
        for node in self._list:
            node.close()

    def from_local(
        self,
        node_runbook: schema.LocalNode,
        logger_name: str = "node",
    ) -> Node:
        assert isinstance(
            node_runbook, schema.LocalNode
        ), f"actual: {type(node_runbook)}"
        node = Node.create(
            len(self._list),
            capability=node_runbook.capability,
            node_type=node_runbook.type,
            is_default=node_runbook.is_default,
            logger_name=logger_name,
        )
        self._list.append(node)

        return node

    def from_remote(
        self,
        node_runbook: schema.RemoteNode,
        logger_name: str = "node",
    ) -> Optional[Node]:
        assert isinstance(
            node_runbook, schema.RemoteNode
        ), f"actual: {type(node_runbook)}"

        node = Node.create(
            len(self._list),
            capability=node_runbook.capability,
            node_type=node_runbook.type,
            is_default=node_runbook.is_default,
            logger_name=logger_name,
        )
        self._list.append(node)

        fields = [
            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS,
            constants.ENVIRONMENTS_NODES_REMOTE_PORT,
            constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS,
            constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_PORT,
            constants.ENVIRONMENTS_NODES_REMOTE_USERNAME,
            constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD,
            constants.ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE,
        ]
        parameters = fields_to_dict(node_runbook, fields)
        node.set_connection_info(**parameters)

        return node

    def from_requirement(self, node_requirement: schema.NodeSpace) -> Node:
        min_requirement = cast(
            schema.NodeSpace, node_requirement.generate_min_capability(node_requirement)
        )
        assert isinstance(min_requirement.node_count, int), (
            f"must be int after generate_min_capability, "
            f"actual: {min_requirement.node_count}"
        )
        # node count should be expanded in platform already
        assert min_requirement.node_count == 1, f"actual: {min_requirement.node_count}"
        node = Node.create(
            len(self._list),
            capability=min_requirement,
            node_type=constants.ENVIRONMENTS_NODES_REMOTE,
            is_default=node_requirement.is_default,
        )
        self._list.append(node)
        return node
