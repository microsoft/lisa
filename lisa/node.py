# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from random import randint
from typing import Any, Iterable, List, Optional, TypeVar, Union, cast

from lisa import schema
from lisa.executable import Tools
from lisa.feature import Features
from lisa.operating_system import OperatingSystem
from lisa.tools import Echo, Reboot
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

        if self.is_remote:
            self._shell: Optional[Shell] = None
        else:
            self._shell = LocalShell()

        # will be initialized by platform
        self.features: Features
        self.tools = Tools(self)
        self.working_path: PurePath = PurePath()
        node_id = str(self.index) if self.index >= 0 else ""
        self.log = get_logger(logger_name, node_id)

        self._support_sudo: Optional[bool] = None
        self._connection_info: Optional[ConnectionInfo] = None

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
        self._shell = SshShell(self._connection_info)
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
        sudo: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        cwd: Optional[PurePath] = None,
        timeout: int = 600,
    ) -> ExecutableResult:
        process = self.execute_async(
            cmd,
            shell=shell,
            sudo=sudo,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result(timeout=timeout)

    def execute_async(
        self,
        cmd: str,
        shell: bool = False,
        sudo: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        cwd: Optional[PurePath] = None,
    ) -> Process:
        self.initialize()

        if sudo and not self.support_sudo:
            raise LisaException(
                f"node doesn't support [command] or [sudo], cannot execute: {cmd}"
            )

        return self._execute(
            cmd,
            shell=shell,
            sudo=sudo,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )

    @property
    def shell(self) -> Shell:
        assert self._shell, "Shell is not initialized"
        return self._shell

    @property
    def is_posix(self) -> bool:
        self.initialize()
        return self.os.is_posix

    @property
    def support_sudo(self) -> bool:
        self.initialize()

        # check if sudo supported
        if self.is_posix and self._support_sudo is None:
            process = self._execute("command -v sudo", shell=True, no_info_log=True)
            result = process.wait_result(10)
            if result.exit_code == 0:
                self._support_sudo = True
            else:
                self._support_sudo = False
                self.log.debug("node doesn't support sudo, may cause failure later.")
        if self._support_sudo is None:
            # set Windows to true to ignore sudo asks.
            self._support_sudo = True

        return self._support_sudo

    @property
    def is_connected(self) -> bool:
        return self._shell is not None and self._shell.is_connected

    def close(self) -> None:
        self.log.debug("closing node connection...")
        if self._shell:
            self._shell.close()

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
            if self.is_posix:
                remote_root_path = Path("$HOME")
            else:
                remote_root_path = Path("%TEMP%")
            working_path = remote_root_path.joinpath(
                constants.PATH_REMOTE_ROOT, constants.RUN_LOGIC_PATH
            ).as_posix()

            # expand environment variables in path
            echo = self.tools[Echo]
            result = echo.run(working_path, shell=True)

            # PurePath is more reasonable here, but spurplus doesn't support it.
            if self.is_posix:
                self.working_path = PurePosixPath(result.stdout)
            else:
                self.working_path = PureWindowsPath(result.stdout)
        else:
            self.working_path = constants.RUN_LOCAL_PATH

        self.shell.mkdir(self.working_path, parents=True, exist_ok=True)
        self.log.debug(f"working path is: '{self.working_path}'")

    def _execute(
        self,
        cmd: str,
        shell: bool = False,
        sudo: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[PurePath] = None,
    ) -> Process:
        cmd_id = str(randint(0, 10000))
        process = Process(cmd_id, self.shell, parent_logger=self.log)
        process.start(
            cmd,
            shell=shell,
            sudo=sudo,
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
