# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from random import randint
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Union, cast

from lisa import schema
from lisa.executable import Tools
from lisa.feature import Features
from lisa.nic import Nics
from lisa.operating_system import OperatingSystem
from lisa.tools import Echo, Lsblk, Mkfs, Mount, Reboot, Uname
from lisa.tools.mkfs import FileSystem
from lisa.util import (
    ContextMixin,
    InitializableMixin,
    LisaException,
    constants,
    fields_to_dict,
    get_datetime_path,
    hookimpl,
    hookspec,
    plugin_manager,
    subclasses,
)
from lisa.util.constants import PATH_REMOTE_ROOT
from lisa.util.logger import Logger, create_file_handler, get_logger, remove_handler
from lisa.util.parallel import run_in_parallel
from lisa.util.process import ExecutableResult, Process
from lisa.util.shell import LocalShell, Shell, SshShell

T = TypeVar("T")
__local_node: Optional[Node] = None


class Node(subclasses.BaseClassWithRunbookMixin, ContextMixin, InitializableMixin):
    _factory: Optional[subclasses.Factory[Node]] = None

    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        is_test_target: bool = True,
        base_part_path: Optional[Path] = None,
        parent_logger: Optional[Logger] = None,
    ) -> None:
        super().__init__(runbook=runbook)
        self.is_default = runbook.is_default
        self.capability = runbook.capability
        self.name = runbook.name
        self.is_test_target = is_test_target
        self.index = index
        self.provision_time: float
        self._shell: Optional[Shell] = None
        self._first_initialize: bool = False

        # will be initialized by platform
        self.features: Features
        self.tools = Tools(self)
        # the path uses remotely
        node_id = str(self.index) if self.index >= 0 else ""
        self.log = get_logger(logger_name, node_id, parent=parent_logger)

        # to be initialized when it's first used.
        self._nics: Optional[Nics] = None

        # The working path will be created in remote node, when it's used.
        self._working_path: Optional[PurePath] = None

        # Not to set the log path until its first used. Because the path
        # contains node name, which is not set in __init__.
        self._base_part_path: Path = base_part_path if base_part_path else Path()
        self._local_log_path: Optional[Path] = None
        self._local_working_path: Optional[Path] = None
        self._support_sudo: Optional[bool] = None
        self._is_dirty: bool = False

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
            part_name = self._get_node_part_path()
            log_path = constants.RUN_LOCAL_LOG_PATH / self._base_part_path / part_name
            self._local_log_path = log_path
            self._local_log_path.mkdir(parents=True, exist_ok=True)

        return self._local_log_path

    @property
    def local_working_path(self) -> Path:
        if not self._local_working_path:
            part_name = self._get_node_part_path()
            self._local_working_path = (
                constants.RUN_LOCAL_WORKING_PATH / self._base_part_path / part_name
            )
            self._local_working_path.mkdir(parents=True, exist_ok=True)

        return self._local_working_path

    @property
    def working_path(self) -> PurePath:
        """
        The working path may be a remote path on remote node. It uses to put executable.
        """
        if not self._working_path:
            self._working_path = self.get_working_path()

            self.shell.mkdir(self._working_path, parents=True, exist_ok=True)
            self.log.debug(f"working path is: '{self._working_path}'")

        return self._working_path

    @property
    def nics(self) -> Nics:
        if self._nics is None:
            self._nics = Nics(self)
            self._nics.initialize()

        return self._nics

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    @classmethod
    def create(
        cls,
        index: int,
        runbook: schema.Node,
        logger_name: str = "node",
        is_test_target: bool = True,
        base_part_path: Optional[Path] = None,
        parent_logger: Optional[Logger] = None,
    ) -> Node:
        if not cls._factory:
            cls._factory = subclasses.Factory[Node](Node)

        node = cls._factory.create_by_runbook(
            index=index,
            runbook=runbook,
            logger_name=logger_name,
            is_test_target=is_test_target,
            base_part_path=base_part_path,
            parent_logger=parent_logger,
        )

        node.log.debug(
            f"created, type: '{node.__class__.__name__}', default: {runbook.is_default}"
            f", is_test_target: {is_test_target}"
        )
        return node

    def reboot(self, time_out: int = 300) -> None:
        self.tools[Reboot].reboot(time_out)

    def execute(
        self,
        cmd: str,
        shell: bool = False,
        sudo: bool = False,
        nohup: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        no_debug_log: bool = False,
        cwd: Optional[PurePath] = None,
        timeout: int = 600,
        update_envs: Optional[Dict[str, str]] = None,
        expected_exit_code: Optional[int] = None,
        expected_exit_code_failure_message: str = "",
    ) -> ExecutableResult:
        process = self.execute_async(
            cmd,
            shell=shell,
            sudo=sudo,
            nohup=nohup,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            no_debug_log=no_debug_log,
            cwd=cwd,
            update_envs=update_envs,
        )
        return process.wait_result(
            timeout=timeout,
            expected_exit_code=expected_exit_code,
            expected_exit_code_failure_message=expected_exit_code_failure_message,
        )

    def execute_async(
        self,
        cmd: str,
        shell: bool = False,
        sudo: bool = False,
        nohup: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        no_debug_log: bool = False,
        cwd: Optional[PurePath] = None,
        update_envs: Optional[Dict[str, str]] = None,
    ) -> Process:
        self.initialize()

        return self._execute(
            cmd,
            shell=shell,
            sudo=sudo and self.support_sudo,
            nohup=nohup,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            no_debug_log=no_debug_log,
            cwd=cwd,
            update_envs=update_envs,
        )

    def cleanup(self) -> None:
        self.log.debug("cleaning up...")
        if hasattr(self, "_log_handler") and self._log_handler:
            remove_handler(self._log_handler, self.log)
            self._log_handler.close()

    def close(self) -> None:
        self.log.debug("closing node connection...")
        if self._shell:
            self._shell.close()
        if self._nics:
            self._nics = None

    def get_pure_path(self, path: str) -> PurePath:
        # spurplus doesn't support PurePath, so it needs to resolve by the
        # node's os here.
        if self.is_posix:
            return PurePosixPath(path)
        else:
            return PureWindowsPath(path)

    def get_case_working_path(self, case_unique_name: str) -> PurePath:
        working_path = self.working_path / "tests" / case_unique_name
        self.shell.mkdir(path=working_path, exist_ok=True)

        return working_path

    def capture_system_information(self, name: str = "") -> None:
        """
        download key files or outputs of commands to a subfolder of the node.
        """
        saved_path = self.local_log_path / f"{get_datetime_path()}_captured_{name}"
        saved_path.mkdir(parents=True, exist_ok=True)
        self.log.debug(f"capturing system information to {saved_path}.")
        self.os.capture_system_information(saved_path)

    def find_partition_with_freespace(
        self, size_in_gb: int, use_os_drive: bool = True
    ) -> str:
        if self.os.is_windows:
            raise NotImplementedError(
                (
                    "find_partition_with_freespace was called on a Windows "
                    "node, this function is not implemented for Windows"
                )
            )

        mount = self.tools[Mount]
        lsblk = self.tools[Lsblk]
        disks = lsblk.get_disks()

        # find a disk/partition with required space
        for disk in disks:
            if disk.is_os_disk and not use_os_drive:
                continue

            # if the disk contains partition, check the partitions
            if len(disk.partitions) > 0:
                for partition in disk.partitions:
                    # we only use root partition for OS disk
                    if disk.is_os_disk and partition.mountpoint != "/":
                        continue

                    if not partition.size_in_gb >= size_in_gb:
                        continue

                    # mount partition if it is not mounted
                    partition_name = partition.name
                    if not partition.is_mounted:
                        mountpoint = f"{PATH_REMOTE_ROOT}/{partition_name}"
                        mount.mount(partition.device_name, mountpoint, format_=True)
                    else:
                        mountpoint = partition.mountpoint

                    # some distro use absolute path wrt to the root, so we need to
                    # requery the mount point after mounting
                    return lsblk.find_mountpoint_by_volume_name(
                        partition_name, force_run=True
                    )
            else:
                if not disk.size_in_gb >= size_in_gb:
                    continue

                # mount the disk if it isn't mounted
                disk_name = disk.name
                if not disk.is_mounted:
                    mountpoint = f"{PATH_REMOTE_ROOT}/{disk_name}"
                    self.tools[Mkfs].format_disk(disk.device_name, FileSystem.ext4)
                    mount.mount(disk.device_name, mountpoint, format_=True)
                else:
                    mountpoint = disk.mountpoint

                # some distro use absolute path wrt to the root, so we need to requery
                # the mount point after mounting
                return lsblk.find_mountpoint_by_volume_name(disk_name, force_run=True)

        raise LisaException(
            f"No partition with Required disk space of {size_in_gb}GB found"
        )

    def get_working_path(self) -> PurePath:
        """
        It returns the path with expanded environment variables, but not create
        the folder. So, it can be used to locate a relative path from it, and
        not create extra folders.
        """
        raise NotImplementedError()

    def mark_dirty(self) -> None:
        self.log.debug("mark node to dirty")
        self._is_dirty = True

    def test_connection(self) -> bool:
        try:
            self.execute("date")
            return True
        except Exception as identifier:
            self.log.debug(f"cannot access VM {self.name}, error is {identifier}")
        return False

    def check_kernel_panic(self) -> None:
        from lisa.features import SerialConsole

        if self.features.is_supported(SerialConsole):
            serial_console = self.features[SerialConsole]
            serial_console.check_panic(
                saved_path=None, stage="after_case", force_run=True
            )

    def get_information(self) -> Dict[str, str]:
        final_information: Dict[str, str] = {}
        informations: List[Dict[str, str]] = plugin_manager.hook.get_node_information(
            node=self
        )
        informations.reverse()
        for current_information in informations:
            final_information.update(current_information)

        return final_information

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if not hasattr(self, "_log_handler"):
            self._log_handler = create_file_handler(
                self.local_log_path / "node.log", self.log
            )
            self._first_initialize = True
        self.log.info(f"initializing node '{self.name}' {self}")
        self.shell.initialize()
        self.os: OperatingSystem = OperatingSystem.create(self)
        self.capture_system_information("started")

    def _execute(
        self,
        cmd: str,
        shell: bool = False,
        sudo: bool = False,
        nohup: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        no_debug_log: bool = False,
        cwd: Optional[PurePath] = None,
        update_envs: Optional[Dict[str, str]] = None,
    ) -> Process:
        cmd_id = str(randint(0, 10000))
        process = Process(cmd_id, self.shell, parent_logger=self.log)
        process.start(
            cmd,
            shell=shell,
            sudo=sudo,
            nohup=nohup,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            no_debug_log=no_debug_log,
            cwd=cwd,
            update_envs=update_envs,
        )
        return process

    def _get_node_part_path(self) -> PurePath:
        path_name = self.name
        if not path_name:
            if self.index:
                index = self.index
            else:
                index = randint(0, 10000)
            path_name = f"node-{index}"
        return PurePath(path_name)


class RemoteNode(Node):
    def __repr__(self) -> str:
        # it's used to handle UT failure.
        if hasattr(self, "_connection_info"):
            return str(self._connection_info)
        return ""

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
            constants.ENVIRONMENTS_NODES_REMOTE_USE_PUBLIC_ADDRESS,
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
        use_public_address: bool = True,
        public_address: str = "",
        public_port: Optional[int] = 22,
        username: str = "root",
        password: str = "",
        private_key_file: str = "",
    ) -> None:
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

        self._connection_info: schema.ConnectionInfo = schema.ConnectionInfo(
            public_address if use_public_address else address,
            public_port if use_public_address else port,
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

    def get_working_path(self) -> PurePath:
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

        return self.get_pure_path(result.stdout)


class LocalNode(Node):
    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        base_part_path: Optional[Path],
        is_test_target: bool = True,
        parent_logger: Optional[Logger] = None,
    ) -> None:
        super().__init__(
            index=index,
            runbook=runbook,
            logger_name=logger_name,
            is_test_target=is_test_target,
            base_part_path=base_part_path,
            parent_logger=parent_logger,
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

    def get_working_path(self) -> PurePath:
        return self.local_working_path

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
        run_in_parallel([x.initialize for x in self._list])

    def close(self) -> None:
        for node in self._list:
            node.close()

    def cleanup(self) -> None:
        for node in self._list:
            node.cleanup()

    def append(self, node: Node) -> None:
        self._list.append(node)

    def test_connections(self) -> bool:
        return all(run_in_parallel([x.test_connection for x in self._list]))

    def check_kernel_panics(self) -> None:
        run_in_parallel([x.check_kernel_panic for x in self._list])


def local_node_connect(
    index: int = -1,
    name: str = "local",
    base_part_path: Optional[Path] = None,
    parent_logger: Optional[Logger] = None,
) -> Node:
    node_runbook = schema.LocalNode(name=name, capability=schema.Capability())
    node = Node.create(
        index=index,
        runbook=node_runbook,
        logger_name=name,
        is_test_target=False,
        base_part_path=base_part_path,
        parent_logger=parent_logger,
    )
    node.initialize()
    return node


def local() -> Node:
    """
    Return a default local node. There is no special configuration.
    """
    global __local_node
    if __local_node is None:
        __local_node = local_node_connect()
    return __local_node


def quick_connect(
    runbook: schema.Node,
    logger_name: str = "",
    index: int = -1,
    parent_logger: Optional[Logger] = None,
) -> Node:
    """
    setup node information and initialize connection.
    """
    node = Node.create(
        index,
        runbook,
        is_test_target=False,
        logger_name=logger_name,
        parent_logger=parent_logger,
    )
    if isinstance(node, RemoteNode):
        node.set_connection_info_by_runbook()
    node.initialize()

    return node


class NodeHookSpec:
    @hookspec
    def get_node_information(self, node: Node) -> Dict[str, str]:
        ...


class NodeHookImpl:
    @hookimpl
    def get_node_information(self, node: Node) -> Dict[str, str]:
        information: Dict[str, str] = {}

        if node:
            try:
                if node.is_connected and node.is_posix:
                    linux_information = node.tools[Uname].get_linux_information()
                    information_dict = fields_to_dict(
                        linux_information, fields=["hardware_platform"]
                    )
                    information.update(information_dict)
                    information["distro_version"] = node.os.information.full_version
                    information["kernel_version"] = linux_information.kernel_version_raw
            except Exception as identifier:
                node.log.exception(
                    "failed to get node information", exc_info=identifier
                )

        return information


plugin_manager.add_hookspecs(NodeHookSpec)
plugin_manager.register(NodeHookImpl())
