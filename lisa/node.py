# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from random import randint
from typing import Any, Iterable, List, Optional, Type, Union

from lisa import schema
from lisa.executable import Tools
from lisa.feature import Features
from lisa.operating_system import OperatingSystem
from lisa.tools import Echo, Reboot
from lisa.util import ContextMixin, InitializableMixin, LisaException, constants
from lisa.util.logger import get_logger
from lisa.util.process import ExecutableResult, Process
from lisa.util.shell import ConnectionInfo, LocalShell, Shell, SshShell
from lisa.util.subclasses import BaseClassWithRunbookMixin, Factory


class Node(BaseClassWithRunbookMixin, ContextMixin, InitializableMixin):
    def __init__(
        self,
        index: int,
        runbook: schema.Node,
        logger_name: str,
        base_log_path: Optional[Path] = None,
    ) -> None:
        super().__init__(runbook=runbook)
        self.is_default = runbook.is_default
        self.capability = runbook.capability
        self.name = runbook.name
        self.index = index

        # will be initialized by platform
        self.features: Features
        self.tools = Tools(self)
        # the path uses remotely
        node_id = str(self.index) if self.index >= 0 else ""
        self.log = get_logger(logger_name, node_id)

        # The working path will be created in remote node, when it's used.
        self._working_path: Optional[PurePath] = None
        self._base_local_log_path = base_log_path
        # Not to set the log path until its first used. Because the path
        # contains node name, which is not set in __init__.
        self._local_log_path: Optional[Path] = None
        self._support_sudo: Optional[bool] = None
        self._connection_info: Optional[ConnectionInfo] = None
        self._shell: Optional[Union[LocalShell, SshShell]] = None
        self.log.debug(f"adding new node {self.name}, is_default: {self.is_default}")

    def __str__(self) -> str:
        raise NotImplementedError("base node class not meant to be used directly")

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.Node

    @property
    def working_path(self) -> PurePath:
        raise NotImplementedError("base node class not meant to be used directly")

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
                f"{self} doesn't support [command] or [sudo], cannot execute: {cmd}"
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
                self.log.debug(
                    f"{self} doesn't support sudo, it may cause failures later."
                )
        if self._support_sudo is None:
            # set Windows to true to ignore sudo asks.
            self._support_sudo = True

        return self._support_sudo

    @property
    def is_connected(self) -> bool:
        return self._shell is not None and self._shell.is_connected

    @property
    def local_log_path(self) -> Path:
        if not self._local_log_path:
            base_path = self._base_local_log_path
            if not base_path:
                base_path = constants.RUN_LOCAL_PATH
            path_name = self.name
            if not path_name:
                if self.index:
                    index = self.index
                else:
                    index = randint(0, 10000)
                path_name = f"node-{index}"
            self._local_log_path = base_path / path_name
            if self._local_log_path.exists():
                raise LisaException(
                    "Conflicting node log path detected, "
                    "make sure LISA invocations have individual runtime paths."
                    f"'{self._local_log_path}'"
                )
            self._local_log_path.mkdir(parents=True)

        return self._local_log_path

    # FIXME: local nodes have a LocalShell, unless one sets connection
    # info on them? Finish documenting that
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
                f"{self} is set connection information already, cannot set again"
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

    def close(self) -> None:
        self.log.debug("closing node connection...")
        if self._shell:
            self._shell.close()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.log.info(f"initializing node {self}")
        self.shell.initialize()
        self.os: OperatingSystem = OperatingSystem.create(self)

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


class LocalNode(Node):
    def __init__(
        self,
        index: int,
        runbook: schema.LocalNode,
        logger_name: str,
        base_log_path: Optional[Path] = None,
        name: str = "",
    ) -> None:
        super().__init__(index, runbook, logger_name)
        self._shell = LocalShell()

    @classmethod
    def type_name(cls) -> str:
        return constants.ENVIRONMENTS_NODES_LOCAL

    def __str__(self) -> str:
        return f"{self.name if self.name else 'unnamed'}" + "[local]"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.LocalNode

    @property
    def working_path(self) -> PurePath:
        if self._working_path:
            return self._working_path

        self._working_path = constants.RUN_LOCAL_PATH

        self.shell.mkdir(self._working_path, parents=True, exist_ok=True)
        self.log.debug(f"working path is: '{self._working_path}'")

        return self._working_path


class RemoteNode(Node):
    def __init__(
        self,
        index: int,
        runbook: schema.RemoteNode,
        logger_name: str,
        base_log_path: Optional[Path] = None,
        name: str = "",
        with_conn_info: bool = True,
    ) -> None:
        super().__init__(index, runbook, logger_name)
        if not with_conn_info:
            return
        self.set_connection_info(
            public_address=runbook.public_address,
            public_port=runbook.public_port,
            username=runbook.username,
            password=runbook.password,
            private_key_file=runbook.private_key_file,
        )

    @classmethod
    def type_name(cls) -> str:
        return constants.ENVIRONMENTS_NODES_REMOTE

    def __str__(self) -> str:
        return (
            f"{self.name if self.name else 'unnamed'}[remote]--{self._connection_info}"
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        assert (
            self._connection_info
        ), "call set_connection_info before using a remote node"
        super()._initialize(args, kwargs)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.RemoteNode

    @property
    def working_path(self) -> PurePath:
        if self._working_path:
            return self._working_path

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
            self._working_path = PurePosixPath(result.stdout)
        else:
            self._working_path = PureWindowsPath(result.stdout)

        self.shell.mkdir(self._working_path, parents=True, exist_ok=True)
        self.log.debug(f"working path is: '{self._working_path}'")

        return self._working_path


class Nodes:
    def __init__(self) -> None:
        super().__init__()
        self._default: Optional[Node] = None
        self._list: List[Node] = list()

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

    def initialize(self) -> None:
        for node in self._list:
            node.initialize()

    def close(self) -> None:
        for node in self._list:
            node.close()

    def from_existing(
        self,
        node_runbook: Union[schema.LocalNode, schema.RemoteNode],
        environment_name: str,
        base_log_path: Optional[Path] = None,
    ) -> Node:
        node: Node = Factory[Node](Node).create_by_type_name(
            node_runbook.type,
            len(self._list),
            runbook=node_runbook,
            logger_name=environment_name,
        )

        self._list.append(node)
        return node

    def from_requirement(
        self,
        node_requirement: schema.NodeSpace,
        environment_name: str,
        base_log_path: Optional[Path] = None,
    ) -> RemoteNode:
        min_cap = node_requirement.generate_min_capability(node_requirement)
        assert isinstance(min_cap.node_count, int), (
            f"must be int after generate_min_capability, "
            f"actual: {min_cap.node_count}"
        )
        # node count should be expanded in platform already
        assert min_cap.node_count == 1, f"actual: {min_cap.node_count}"
        sch = schema.RemoteNode(_ignore_conn=True)
        sch.capability = min_cap
        sch.is_default = min_cap.is_default

        node = RemoteNode(
            len(self._list),
            sch,
            base_log_path=base_log_path,
            logger_name=environment_name,
            with_conn_info=False,
        )
        self._list.append(node)
        return node


def is_remote(node: Node) -> bool:
    return isinstance(node, RemoteNode)
