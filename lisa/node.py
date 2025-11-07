# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from random import randint
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    cast,
)

from lisa import schema
from lisa.executable import Tools
from lisa.feature import Features
from lisa.nic import Nics, NicsBSD
from lisa.operating_system import OperatingSystem
from lisa.secret import add_secret
from lisa.tools import Chmod, Df, Dmesg, Echo, Lsblk, Mkfs, Mount, Reboot, Uname, Wsl
from lisa.tools.mkfs import FileSystem
from lisa.util import (
    ContextMixin,
    InitializableMixin,
    LisaException,
    RequireUserPasswordException,
    constants,
    fields_to_dict,
    generate_strong_password,
    get_datetime_path,
    hookimpl,
    hookspec,
    plugin_manager,
    subclasses,
)
from lisa.util.constants import PATH_REMOTE_ROOT
from lisa.util.logger import Logger, create_file_handler, get_logger, remove_handler
from lisa.util.parallel import run_in_parallel
from lisa.util.process import ExecutableResult, Process, process_command
from lisa.util.shell import LocalShell, Shell, SshShell, WslShell

T = TypeVar("T")
__local_node: Optional[Node] = None


class Node(subclasses.BaseClassWithRunbookMixin, ContextMixin, InitializableMixin):
    _factory: Optional[subclasses.Factory[Node]] = None

    # [sudo] password for
    # Password:
    _sudo_password_prompts: List[str] = [
        "[sudo] password for",
        "Password:",
    ]

    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        is_test_target: bool = True,
        base_part_path: Optional[Path] = None,
        parent_logger: Optional[Logger] = None,
        encoding: str = "utf-8",
        parent: Optional[Node] = None,
        **kwargs: Any,
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
        self._encoding = encoding
        self._guests: List[Node] = []
        self._parent = parent

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

        if parent:
            self._base_part_path: Path = parent._base_part_path
        else:
            # Not to set the log path until its first used. Because the path
            # contains node name, which is not set in __init__.
            self._base_part_path = base_part_path if base_part_path else Path()

        self._local_log_path: Optional[Path] = None
        self._local_working_path: Optional[Path] = None
        self._support_sudo: Optional[bool] = None
        self._is_dirty: bool = False
        self.capture_boot_time: bool = False
        self.assert_kernel_error_after_test: bool = False
        self.capture_azure_information: bool = False
        self.capture_kernel_config: bool = False
        self.has_checked_bash_prompt: bool = False

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
        # self._support_sudo already set, return it directly.
        if self._support_sudo is not None:
            return self._support_sudo

        if self.is_posix:
            self._support_sudo = self._check_sudo_available()
        else:
            # set Windows to true to ignore sudo asks.
            self._support_sudo = True

        return self._support_sudo

    def _check_sudo_available(self) -> bool:
        # Check if 'sudo' command exists
        process = self._execute("command -v sudo", shell=True, no_info_log=True)
        result = process.wait_result(10)
        if result.exit_code != 0:
            self.log.debug("node doesn't support 'sudo', may cause failure later.")
            return False

        # Further test: try running 'ls' with sudo /bin/sh
        process = self._execute("ls", shell=True, sudo=True, no_info_log=True)
        result = process.wait_result(10)
        if result.exit_code != 0:
            # e.g. raw error: "user is not allowed to execute '/bin/sh -c ...'"
            if "not allowed" in result.stderr:
                self.log.debug(
                    "The command 'sudo /bin/sh -c ls' may fail due to SELinux policies"
                    " that restrict the use of sudo in combination with /bin/sh."
                )
                return False

        return True

    @property
    def parent(self) -> Optional[Node]:
        return self._parent

    @property
    def guests(self) -> List[Node]:
        return self._guests

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
            self._nics = create_nics(self)
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
        parent: Optional["Node"] = None,
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
            parent=parent,
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
        encoding: str = "",
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
            encoding=encoding,
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
        encoding: str = "",
    ) -> Process:
        self.initialize()
        if isinstance(self, RemoteNode):
            self._check_bash_prompt()

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
            encoding=encoding,
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

    def get_str_path(self, path: Union[PurePath, str]) -> str:
        # normalize str path to pure path for next step.
        if isinstance(path, str):
            path = self.get_pure_path(path)

        # convert to path format of the system.
        if self.is_posix:
            return path.as_posix()
        else:
            return str(PureWindowsPath(path))

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
        try:
            self.os.capture_system_information(saved_path)
        except Exception as e:
            # For some images like cisco, southrivertech1586314123192, they might raise
            # exception when calling copy_back. This should not block the test, so add
            # try-except.
            self.log.debug(f"error on capturing system information: {e}")

    def find_partition_with_freespace(
        self, size_in_gb: int, use_os_drive: bool = True, raise_error: bool = True
    ) -> str:
        self.initialize()
        if self.os.is_windows:
            raise NotImplementedError(
                (
                    "find_partition_with_freespace was called on a Windows "
                    "node, this function is not implemented for Windows"
                )
            )

        lsblk = self.tools[Lsblk]
        disks = lsblk.get_disks(force_run=True)
        df = self.tools[Df]

        # find a disk/partition with required space
        for disk in disks:
            mountpoint = ""
            if disk.is_os_disk and not use_os_drive:
                continue

            # if the disk contains partition, check the partitions only.
            if disk.partitions:
                for partition in disk.partitions:
                    # we only use root partition for OS disk
                    if disk.is_os_disk and partition.mountpoint != "/":
                        continue

                    # mount partition if it is not mounted
                    disk_name = partition_name = partition.name
                    if not partition.is_mounted:
                        mountpoint = f"{PATH_REMOTE_ROOT}/{partition_name}"
                        mount = self.tools[Mount]
                        mount.mount(partition.device_name, mountpoint, format_=True)
                    else:
                        mountpoint = partition.mountpoint
            else:
                # mount the disk if it isn't mounted
                disk_name = disk.name
                if "fd" in disk_name:
                    # skip floppy disk
                    continue
                if disk.fstype == "swap":
                    # skip swap disk
                    continue

                if disk.size_in_gb < size_in_gb:
                    # skip smaller size disk, instead of format it automatically.
                    self.log.debug(
                        f"skip disk {disk_name}, size {disk.size_in_gb} is too small."
                    )
                    continue

                if not disk.is_mounted:
                    mountpoint = f"{PATH_REMOTE_ROOT}/{disk_name}"
                    self.tools[Mkfs].format_disk(disk.device_name, FileSystem.ext4)
                    mount = self.tools[Mount]
                    mount.mount(disk.device_name, mountpoint, format_=True)
                else:
                    mountpoint = disk.mountpoint

            if (
                mountpoint
                and df.get_filesystem_available_space(mountpoint, True) >= size_in_gb
            ):
                # some distro use absolute path wrt to the root, so we need to requery
                # the mount point after mounting
                return lsblk.find_mountpoint_by_volume_name(disk_name, force_run=True)

        if raise_error:
            raise LisaException(
                f"No partition with Required disk space of {size_in_gb}GB found"
            )

        return ""

    def get_working_path_with_required_space(self, required_size_in_gb: int) -> str:
        work_path = str(self.working_path)
        df = self.tools[Df]
        lisa_path_space = df.get_filesystem_available_space(work_path)
        if lisa_path_space < required_size_in_gb:
            work_path = self.find_partition_with_freespace(required_size_in_gb)
            self.tools[Chmod].chmod(work_path, "777", sudo=True)
        return work_path

    def get_working_path(self) -> PurePath:
        """
        It returns the path with expanded environment variables, but not create
        the folder. So, it can be used to locate a relative path from it, and
        not create extra folders.
        """
        raise NotImplementedError()

    def _get_remote_working_path(self) -> PurePath:
        if self.is_posix:
            remote_root_path = Path("$HOME")
        else:
            remote_root_path = Path("%TEMP%")

        working_path = remote_root_path.joinpath(
            constants.PATH_REMOTE_ROOT, constants.RUN_LOGIC_PATH
        ).as_posix()

        # expand environment variables in path
        return self.get_pure_path(self.expand_env_path(working_path))

    def mark_dirty(self) -> None:
        self.log.debug("mark node to dirty")
        self._is_dirty = True

    def test_connection(self) -> bool:
        assert self._shell
        if not self._shell.is_remote:
            return True
        self.log.debug("testing connection...")
        try:
            self.execute("echo connected", timeout=10)
            return True
        except Exception as e:
            self.log.debug(f"cannot access VM {self.name}, error is {e}")
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

    def check_kernel_error(self) -> None:
        # Check if the kernel is in a healthy state without errors or panics.
        dmesg = self.tools[Dmesg]
        dmesg.check_kernel_errors(force_run=True, throw_error=True)
        self.check_kernel_panic()

    def expand_env_path(self, raw_path: str) -> str:
        echo = self.tools[Echo]
        result = echo.run(raw_path, shell=True)
        return result.stdout

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
        encoding: str = "",
        command_splitter: Callable[..., List[str]] = process_command,
    ) -> Process:
        cmd_id = str(randint(0, 10000))
        if not encoding:
            encoding = self._encoding
        process = Process(cmd_id, self.shell, parent_logger=self.log)
        process.start(
            cmd,
            shell=shell,
            sudo=sudo,
            nohup=nohup,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            no_debug_log=no_debug_log,
            encoding=encoding,
            cwd=cwd,
            update_envs=update_envs,
            command_splitter=command_splitter,
        )
        return process

    def _get_node_part_path(self) -> PurePath:
        path_name = self.name
        if not path_name:
            if self.index >= 0:
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
        return self._get_remote_working_path()

    @property
    def support_sudo(self) -> bool:
        if self._support_sudo is None:
            result = super().support_sudo
            if result and self.is_posix:
                self.check_sudo_password_required()
            return result
        return self._support_sudo

    def check_sudo_password_required(self) -> None:
        # check if password is required when running command with sudo
        require_sudo_password = False
        process = self._execute(
            f"echo {constants.LISA_TEST_FOR_SUDO}",
            shell=True,
            sudo=True,
            no_info_log=True,
        )
        result = process.wait_result(10)
        if result.exit_code != 0:
            for prompt in self._sudo_password_prompts:
                if prompt in result.stdout:
                    require_sudo_password = True
                    break
        if require_sudo_password:
            self.log.debug(
                "Running commands with sudo in this node needs input of password."
            )
            ssh_shell = cast(SshShell, self.shell)
            ssh_shell.is_sudo_required_password = True
            if not ssh_shell.connection_info.password:
                self.log.info(
                    "Running commands with sudo requires user's password,"
                    " but no password is provided. Need reset a password"
                )
                if not self._reset_password():
                    raise RequireUserPasswordException("Reset password failed")
            self._check_password_and_store_prompt()

    def _check_password_and_store_prompt(self) -> None:
        # self.shell.is_sudo_required_password is true, so running sudo command
        # will input password in process.wait_result. Check running sudo again
        # and get password prompts. For most images, after inputting a password
        # successfully, the prompt is changed when running sudo command again.
        # So check twice to get two kinds of prompt
        password_prompts = []
        for i in range(1, 3):
            process = self._execute(
                f"echo {constants.LISA_TEST_FOR_SUDO}",
                shell=True,
                sudo=True,
                no_info_log=True,
            )
            result = process.wait_result(10)
            if result.exit_code != 0:
                raise RequireUserPasswordException(
                    "The password might be invalid for running sudo command"
                )
            password_prompt = result.stdout.replace(
                f"{constants.LISA_TEST_FOR_SUDO}", ""
            )
            password_prompts.append(password_prompt)
            self.log.debug(f"password prompt {i}: {password_prompt}")
        ssh_shell = cast(SshShell, self.shell)
        ssh_shell.password_prompts = password_prompts

    def _check_bash_prompt(self) -> None:
        # Check if there is bash prompt in stdout of command. If yes, the prompt
        # should be filtered from the stdout. E.g. image yaseensmarket1645449809728
        # wordpress-red-hat images.
        if not self.has_checked_bash_prompt:
            process = self._execute(f"echo {constants.LISA_TEST_FOR_BASH_PROMPT}")
            result = process.wait_result(10)
            if result.stdout.endswith(f"{constants.LISA_TEST_FOR_BASH_PROMPT}"):
                bash_prompt = result.stdout.replace(
                    constants.LISA_TEST_FOR_BASH_PROMPT, ""
                )
                if bash_prompt:
                    self.log.debug(
                        "detected bash prompt, it will be removed from every output: "
                        f"{bash_prompt}"
                    )
                    ssh_shell = cast(SshShell, self.shell)
                    ssh_shell.bash_prompt = bash_prompt
            self.has_checked_bash_prompt = True

    def _reset_password(self) -> bool:
        from lisa.features import PasswordExtension

        if not hasattr(self, "features"):
            return False

        if not self.features.is_supported(PasswordExtension):
            return False
        password_extension = self.features[PasswordExtension]
        username = self._connection_info.username
        password = self._connection_info.password
        if not password:
            password = generate_strong_password()
        try:
            password_extension.reset_password(username, str(password))
        except Exception as e:
            self.log.debug(f"reset password failed: {e}")
            return False
        add_secret(password)
        self._connection_info.password = password
        ssh_shell = cast(SshShell, self.shell)
        ssh_shell.connection_info.password = password
        return True


class LocalNode(Node):
    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        is_test_target: bool = True,
        base_part_path: Optional[Path] = None,
        parent_logger: Optional[Logger] = None,
        encoding: str = "utf-8",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            runbook=runbook,
            index=index,
            logger_name=logger_name,
            is_test_target=is_test_target,
            base_part_path=base_part_path,
            parent_logger=parent_logger,
            encoding=encoding,
            **kwargs,
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


class GuestNode(Node):
    __PARENT_ASSERT_MESSAGE = "guest node must have a parent node."

    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        is_test_target: bool = True,
        base_part_path: Path | None = None,
        parent_logger: Logger | None = None,
        encoding: str = "utf-8",
        parent: Optional[Node] = None,
        **kwargs: Any,
    ) -> None:
        if not parent_logger and parent:
            parent_logger = parent.log

        super().__init__(
            runbook=runbook,
            index=index,
            logger_name=logger_name,
            is_test_target=is_test_target,
            base_part_path=base_part_path,
            parent_logger=parent_logger,
            encoding=encoding,
            parent=parent,
            **kwargs,
        )
        assert self._parent, self.__PARENT_ASSERT_MESSAGE

        self.name = f"g{self.index}"

        self._shell = self._parent._shell

    @classmethod
    def type_name(cls) -> str:
        return "guest_node"

    @property
    def is_remote(self) -> bool:
        assert self._parent, self.__PARENT_ASSERT_MESSAGE
        return self._parent.is_remote

    def cleanup(self) -> None:
        # do nothing on log handlers
        ...

    def _get_node_part_path(self) -> PurePath:
        assert self._parent, self.__PARENT_ASSERT_MESSAGE
        path_name = self._parent._get_node_part_path() / self.name

        return path_name

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # provision before initialize other parts
        self._provision()

        assert self._parent, self.__PARENT_ASSERT_MESSAGE
        self._parent.initialize(*args, **kwargs)
        # os can be initialized earlier in subclasses. If not, initialize it here.
        if not hasattr(self, "os"):
            self.os: OperatingSystem = OperatingSystem.create(self)

        self.capture_system_information("started")

    def _provision(self) -> None:
        ...

    def get_working_path(self) -> PurePath:
        return self._get_remote_working_path()


class WslContainerNode(GuestNode):
    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        is_test_target: bool = True,
        base_part_path: Path | None = None,
        parent_logger: Logger | None = None,
        encoding: str = "utf-8",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            runbook=runbook,
            index=index,
            logger_name=logger_name,
            is_test_target=is_test_target,
            base_part_path=base_part_path,
            parent_logger=parent_logger,
            encoding=encoding,
            **kwargs,
        )

        wsl_runbook = cast(schema.WslNode, runbook)
        assert self._parent, self.__PARENT_ASSERT_MESSAGE
        assert self._parent._shell, "parent node must have the shell."
        self._shell = WslShell(
            parent=self._parent._shell, distro_name=wsl_runbook.distro
        )

    @classmethod
    def type_name(cls) -> str:
        return "wsl"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.WslNode

    def reboot(self, time_out: int = 300) -> None:
        self._wsl.shutdown_distro(self._distro)

    def _provision(self) -> None:
        assert self.parent, self.__PARENT_ASSERT_MESSAGE

        runbook = cast(schema.WslNode, self.runbook)

        # Reinitialize parent node connection, because sometimes the connection
        # is corrupted due to distro is not installed correctly.
        self.parent.close()

        # initialize wsl tool to check if wsl installed
        wsl: Wsl = self.parent.tools.create(Wsl, guest=self)
        self._wsl = wsl
        self._distro = runbook.distro

        wsl.install_distro(
            name=self.runbook.distro, reinstall=runbook.reinstall, kernel=runbook.kernel
        )

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
        encoding: str = "",
        command_splitter: Callable[..., List[str]] = process_command,
    ) -> Process:
        assert self.parent, self.__PARENT_ASSERT_MESSAGE

        cwd_commands: List[str] = []
        if cwd:
            # preprocess cwd, and ignore it from parent's command.
            cwd_commands.append("--cd")
            cwd_commands.append(str(PurePosixPath(cwd)))

        def _get_wsl_cmd(
            is_posix: bool,
            command: str,
            sudo: bool,
            shell: bool,
            nohup: bool,
            update_envs: Dict[str, str],
        ) -> List[str]:
            # change order to support envs
            result: List[str] = []
            if update_envs:
                # set all envs in wsl, not in Windows.
                for key, value in update_envs.items():
                    value = value.replace('"', '\\"')
                    result.append("export")
                    result.append(f"{key}={value}")
                    result.append(";")

                # prevent it's be processed by the other logic in underlying
                # shell.
                update_envs.clear()

            if sudo:
                result += ["sudo"]

            if nohup:
                result += ["nohup"]

            split_cmd = process_command(
                is_posix=True,
                command=command,
                sudo=False,
                shell=shell,
                nohup=False,
                update_envs={},
            )

            if shell and self.is_remote:
                # fix for remote bash commands.
                # assume the original output is like:
                # ['sh', '-c', command]
                last_command = split_cmd[-1].replace('"', '\\"')
                split_cmd[-1] = f'"{last_command}"'

            prefixes = [self._wsl.command, "-d", self._distro]

            if cwd_commands:
                prefixes += cwd_commands

            result = [
                *prefixes,
                "--",
                *result,
                *split_cmd,
            ]

            return result

        return super()._execute(
            cmd=cmd,
            shell=shell,
            sudo=sudo,
            nohup=nohup,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            no_debug_log=no_debug_log,
            cwd=None,
            update_envs=update_envs,
            encoding=encoding,
            command_splitter=_get_wsl_cmd,
        )


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
        yield from self._list

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
            except Exception as e:
                node.log.exception("failed to get node information", exc_info=e)

        return information


plugin_manager.add_hookspecs(NodeHookSpec)
plugin_manager.register(NodeHookImpl())


def create_nics(node: Node) -> Nics:
    """
    Returns a Nics object for the node based on the OS type.
    """
    # Uses uname instead of the node.os because sometimes node.os has not been
    # populated when this is called.
    os = node.execute(cmd="uname", no_error_log=True).stdout
    if "FreeBSD" in os:
        return NicsBSD(node)

    return Nics(node)
