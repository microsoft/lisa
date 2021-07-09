# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from random import randint
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union, cast

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
    subclasses,
)
from lisa.util.logger import get_logger
from lisa.util.process import ExecutableResult, Process
from lisa.util.shell import ConnectionInfo, LocalShell, Shell, SshShell

T = TypeVar("T")


class Node(subclasses.BaseClassWithRunbookMixin, ContextMixin, InitializableMixin):
    _factory: Optional[subclasses.Factory[Node]] = None

    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        base_log_path: Optional[Path] = None,
    ) -> None:
        super().__init__(runbook=runbook)
        self.is_default = runbook.is_default
        self.capability = runbook.capability
        self.name = runbook.name
        self.index = index

        self._shell: Optional[Shell] = None

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

    @property
    def shell(self) -> Shell:
        assert self._shell, "Shell is not initialized"
        return self._shell

    @property
    def is_posix(self) -> bool:
        self.initialize()
        return self.os.is_posix

    @property
    def is_remote(self) -> bool:
        raise NotImplementedError()

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

    @property
    def working_path(self) -> PurePath:
        """
        The working path may be a remote path on remote node. It uses to put executable.
        """
        if not self._working_path:
            self._working_path = self._create_working_path()

            self.shell.mkdir(self._working_path, parents=True, exist_ok=True)
            self.log.debug(f"working path is: '{self._working_path}'")

        return self._working_path

    @classmethod
    def create(
        cls,
        index: int,
        runbook: schema.Node,
        logger_name: str = "node",
        base_log_path: Optional[Path] = None,
    ) -> Node:
        if not cls._factory:
            cls._factory = subclasses.Factory[Node](Node)

        node = cls._factory.create_by_runbook(
            index=index,
            runbook=runbook,
            logger_name=logger_name,
            base_log_path=base_log_path,
        )

        node.log.debug(
            f"created, type: '{node.__class__.__name__}', default: {runbook.is_default}"
        )
        return node

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

    def close(self) -> None:
        self.log.debug("closing node connection...")
        if self._shell:
            self._shell.close()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.log.info(f"initializing node '{self.name}' {self}")
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

    def _create_working_path(self) -> PurePath:
        raise NotImplementedError()


class RemoteNode(Node):
    def __repr__(self) -> str:
        return str(self._connection_info)

    @property
    def is_remote(self) -> bool:
        return True

    @property
    def connection_info(self) -> Dict[str, Any]:
        return fields_to_dict(
            self._connection_info,
            [
                constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS,
                constants.ENVIRONMENTS_NODES_REMOTE_PORT,
                constants.ENVIRONMENTS_NODES_REMOTE_USERNAME,
                constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD,
                constants.ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE,
            ],
            is_none_included=True,
        )

    @classmethod
    def type_name(cls) -> str:
        return constants.ENVIRONMENTS_NODES_REMOTE

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.RemoteNode

    def set_connection_info_by_runbook(
        self,
        default_username: str = "",
        default_password: str = "",
        default_private_key_file: str = "",
    ) -> None:
        fields = [
            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS,
            constants.ENVIRONMENTS_NODES_REMOTE_PORT,
            constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS,
            constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_PORT,
        ]
        parameters = fields_to_dict(self.runbook, fields)

        # use default credential, if they are not specified
        node_runbook = cast(schema.RemoteNode, self.runbook)
        parameters[constants.ENVIRONMENTS_NODES_REMOTE_USERNAME] = (
            node_runbook.username if node_runbook.username else default_username
        )
        parameters[constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD] = (
            node_runbook.password if node_runbook.password else default_password
        )
        parameters[constants.ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE] = (
            node_runbook.private_key_file
            if node_runbook.private_key_file
            else default_private_key_file
        )

        self.set_connection_info(**parameters)

    def set_connection_info(
        self,
        address: str = "",
        port: Optional[int] = 22,
        public_address: str = "",
        public_port: Optional[int] = 22,
        username: str = "root",
        password: str = "",
        private_key_file: str = "",
    ) -> None:
        if hasattr(self, "_connection_info"):
            raise LisaException(
                "node is set connection information already, cannot set again"
            )

        if not address and not public_address:
            raise LisaException(
                "at least one of address and public_address need to be set"
            )
        elif not address:
            address = public_address
        elif not public_address:
            public_address = address

        if not port and not public_port:
            raise LisaException("at least one of port and public_port need to be set")
        elif not port:
            port = public_port
        elif not public_port:
            public_port = port

        assert public_port
        assert port

        self._connection_info: ConnectionInfo = ConnectionInfo(
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

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        assert self._connection_info, "call setConnectionInfo before use remote node"
        super()._initialize(*args, **kwargs)

    def _create_working_path(self) -> PurePath:
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
            result_path: PurePath = PurePosixPath(result.stdout)
        else:
            result_path = PureWindowsPath(result.stdout)
        return result_path


class LocalNode(Node):
    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        base_log_path: Optional[Path],
    ) -> None:
        super().__init__(
            index=index,
            runbook=runbook,
            logger_name=logger_name,
            base_log_path=base_log_path,
        )

        self._shell = LocalShell()

    @property
    def is_remote(self) -> bool:
        return False

    @classmethod
    def type_name(cls) -> str:
        return constants.ENVIRONMENTS_NODES_LOCAL

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.LocalNode

    def _create_working_path(self) -> PurePath:
        return constants.RUN_LOCAL_PATH

    def __repr__(self) -> str:
        return "local"


class Nodes:
    def __init__(self) -> None:
        super().__init__()
        self._default: Optional[Node] = None
        self._list: List[Node] = []

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
        node_runbook: schema.Node,
        environment_name: str,
        base_log_path: Optional[Path] = None,
    ) -> Node:
        node = Node.create(
            index=len(self._list),
            runbook=node_runbook,
            logger_name=environment_name,
            base_log_path=base_log_path,
        )
        self._list.append(node)

        return node

    def from_requirement(
        self,
        node_requirement: schema.NodeSpace,
        environment_name: str,
        base_log_path: Optional[Path] = None,
    ) -> Node:
        min_requirement = cast(
            schema.Capability,
            node_requirement.generate_min_capability(node_requirement),
        )
        assert isinstance(min_requirement.node_count, int), (
            f"must be int after generate_min_capability, "
            f"actual: {min_requirement.node_count}"
        )
        # node count should be expanded in platform already
        assert min_requirement.node_count == 1, f"actual: {min_requirement.node_count}"
        mock_runbook = schema.RemoteNode(
            type=constants.ENVIRONMENTS_NODES_REMOTE,
            capability=min_requirement,
            is_default=node_requirement.is_default,
        )
        node = Node.create(
            index=len(self._list),
            runbook=mock_runbook,
            logger_name=environment_name,
            base_log_path=base_log_path,
        )
        self._list.append(node)

        return node
