# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import os
import shutil
import socket
import sys
from pathlib import Path, PurePath
from time import sleep
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union, cast

import paramiko
import spur  # type: ignore
import spurplus  # type: ignore
from func_timeout import FunctionTimedOut, func_set_timeout  # type: ignore
from paramiko.ssh_exception import SSHException
from retry import retry

from lisa.util import InitializableMixin, LisaException

from .logger import Logger
from .perf_timer import create_timer


def wait_tcp_port_ready(
    address: str, port: int, log: Optional[Logger] = None, timeout: int = 300
) -> Tuple[bool, int]:
    """
    return is ready or not
    """
    is_ready: bool = False
    # TODO: may need to support IPv6.
    times: int = 0
    result: int = 0

    timout_timer = create_timer()
    while timout_timer.elapsed(False) < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
            try:
                result = tcp_socket.connect_ex((address, port))
                if result == 0:
                    is_ready = True
                    break
                else:
                    if times % 10 == 0 and log:
                        log.debug(
                            f"cannot connect to {address}:{port}, "
                            f"error code: {result}, current try: {times + 1},"
                            f" elapsed: {timout_timer.elapsed(False)} "
                            f"(timeout on {timeout}). retrying..."
                        )
                    sleep(1)
                    times += 1
            except Exception as e:
                raise LisaException(f"failed to connect to {address}:{port}: {e}")
    return is_ready, result


class ConnectionInfo:
    def __init__(
        self,
        address: str = "",
        port: int = 22,
        username: str = "root",
        password: Optional[str] = "",
        private_key_file: Optional[str] = None,
    ) -> None:
        self.address = address
        self.port = port
        self.username = username
        self.password = password
        self.private_key_file = private_key_file

        if not self.password and not self.private_key_file:
            raise LisaException(
                "at least one of password or private_key_file need to be set when "
                "connecting"
            )
        elif not self.private_key_file:
            # use password
            # spurplus doesn't process empty string correctly, use None
            self.private_key_file = None
        else:
            if not Path(self.private_key_file).exists():
                raise FileNotFoundError(self.private_key_file)
            self.password = None

        if not self.username:
            raise LisaException("username must be set")

    def __str__(self) -> str:
        return f"{self.username}@{self.address}:{self.port}"


class WindowsShellType(object):
    """
    Windows command generator
    Support get pid, set envs, and cwd
    Doesn't support kill, it needs overwrite spur.SshShell
    """

    supports_which = False

    def generate_run_command(
        self,
        command_args: List[str],
        store_pid: bool = False,
        cwd: Optional[str] = None,
        update_env: Optional[Dict[str, str]] = None,
        new_process_group: bool = False,
    ) -> str:
        commands = []

        if store_pid:
            commands.append(
                'powershell "(gwmi win32_process|? processid -eq $pid).parentprocessid"'
                " &&"
            )

        if cwd is not None:
            commands.append(f"cd {cwd} 2>&1 && echo spur-cd: 0 ")
            commands.append("|| echo spur-cd: 1 && exit 1 &")

        if update_env:
            update_env_commands = [
                "set {0}={1}".format(key, value) for key, value in update_env.items()
            ]
            commands += f"{'& '.join(update_env_commands)}& "

        if cwd is not None:
            commands.append(f"pushd {cwd} & ")
            commands.append(" ".join(command_args))
            commands.append(" & popd")
        else:
            commands.append(" ".join(command_args))
        return " ".join(commands)


# retry strategy is the same as spurplus.connect_with_retries.
@retry(Exception, tries=3, delay=1, logger=None)  # type: ignore
def try_connect(connection_info: ConnectionInfo) -> Any:
    # spur always run a posix command and will fail on Windows.
    # So try with paramiko firstly.
    paramiko_client = paramiko.SSHClient()
    paramiko_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    paramiko_client.connect(
        hostname=connection_info.address,
        port=connection_info.port,
        username=connection_info.username,
        password=connection_info.password,
        key_filename=connection_info.private_key_file,
        banner_timeout=10,
    )
    stdin, stdout, _ = paramiko_client.exec_command("cmd\n")
    # Flush commands and prevent more writes
    stdin.flush()

    # Give it some time to process the command, otherwise reads on
    # stdout on calling contexts have been seen having empty strings
    # from stdout, on Windows. There is a certain 3s penalty on Linux
    # systems, as it's never ready for that (inexisting) command, but
    # that should only happen once per node (not per command)
    tries = 3
    while not stdout.channel.recv_ready() and tries:
        sleep(1)
        tries -= 1

    stdin.channel.shutdown_write()
    paramiko_client.close()

    return stdout


# paramiko stuck on get command output of 'fortinet' VM, and spur hide timeout of
# exec_command. So use an external timeout wrapper to force timeout.
# some images needs longer time to set up ssh connection.
# e.g. Oracle Oracle-Linux 7.5 7.5.20181207
# e.g. qubole-inc qubole-data-service default-img 0.7.4
@func_set_timeout(20)  # type: ignore
def _spawn_ssh_process(shell: spur.ssh.SshShell, **kwargs: Any) -> spur.ssh.SshProcess:
    return shell.spawn(**kwargs)


class SshShell(InitializableMixin):
    def __init__(self, connection_info: ConnectionInfo) -> None:
        super().__init__()
        self.is_remote = True
        self._connection_info = connection_info
        self._inner_shell: Optional[spur.SshShell] = None

        paramiko_logger = logging.getLogger("paramiko")
        paramiko_logger.setLevel(logging.WARN)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        is_ready, tcp_error_code = wait_tcp_port_ready(
            self._connection_info.address, self._connection_info.port
        )
        if not is_ready:
            raise LisaException(
                f"cannot connect to TCP port: "
                f"[{self._connection_info.address}:{self._connection_info.port}], "
                f"error code: {tcp_error_code}"
            )
        try:
            stdout = try_connect(self._connection_info)
        except Exception as identifier:
            raise LisaException(
                f"failed to connect SSH "
                f"[{self._connection_info.address}:{self._connection_info.port}], "
                f"{identifier.__class__.__name__}: {identifier}"
            )

        # Some windows doesn't end the text stream, so read first line only.
        # it's  enough to detect os.
        stdout_content = stdout.readline()
        stdout.close()

        if stdout_content and "Windows" in stdout_content:
            self.is_posix = False
            shell_type = WindowsShellType()
        else:
            self.is_posix = True
            shell_type = spur.ssh.ShellTypes.sh

        spur_kwargs = {
            "hostname": self._connection_info.address,
            "port": self._connection_info.port,
            "username": self._connection_info.username,
            "password": self._connection_info.password,
            "private_key_file": self._connection_info.private_key_file,
            "missing_host_key": spur.ssh.MissingHostKey.accept,
        }

        spur_ssh_shell = spur.SshShell(shell_type=shell_type, **spur_kwargs)
        sftp = spurplus.sftp.ReconnectingSFTP(
            sftp_opener=spur_ssh_shell._open_sftp_client
        )
        self._inner_shell = spurplus.SshShell(spur_ssh_shell=spur_ssh_shell, sftp=sftp)

    def close(self) -> None:
        if self._inner_shell:
            self._inner_shell.close()
            # after closed, can be reconnect
            self._inner_shell = None
        self._is_initialized = False

    @property
    def is_connected(self) -> bool:
        is_inner_shell_ready = False
        if self._inner_shell:
            is_inner_shell_ready = True
        return is_inner_shell_ready

    def spawn(
        self,
        command: Sequence[str],
        update_env: Optional[Mapping[str, str]] = None,
        store_pid: bool = False,
        cwd: Optional[Union[str, Path]] = None,
        stdout: Any = None,
        stderr: Any = None,
        encoding: str = "utf-8",
        use_pty: bool = True,
        allow_error: bool = True,
    ) -> spur.ssh.SshProcess:
        self.initialize()
        assert self._inner_shell

        try:
            process: spur.ssh.SshProcess = _spawn_ssh_process(
                self._inner_shell,
                command=command,
                update_env=update_env,
                store_pid=store_pid,
                cwd=cwd,
                stdout=stdout,
                stderr=stderr,
                encoding=encoding,
                use_pty=use_pty,
                allow_error=allow_error,
            )
        except FunctionTimedOut:
            raise LisaException(
                f"The remote node is timeout on execute {command}. "
                f"It may be caused by paramiko/spur not support the shell of node."
            )
        return process

    def mkdir(
        self,
        path: PurePath,
        mode: int = 0o777,
        parents: bool = True,
        exist_ok: bool = False,
    ) -> None:
        path_str = self._purepath_to_str(path)
        self.initialize()
        assert self._inner_shell
        try:
            self._inner_shell.mkdir(
                path_str, mode=mode, parents=parents, exist_ok=exist_ok
            )
        except PermissionError:
            self._inner_shell.run(command=["sudo", "mkdir", "-p", path_str])
        except SSHException as identifier:
            # no sftp, try commands
            if "Channel closed." in str(identifier):
                assert isinstance(path_str, str)
                self.spawn(command=["mkdir", "-p", path_str])

    def exists(self, path: PurePath) -> bool:
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.exists(path_str))

    def remove(self, path: PurePath, recursive: bool = False) -> None:
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        self._inner_shell.remove(path_str, recursive)

    def chmod(self, path: PurePath, mode: int) -> None:
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        self._inner_shell.chmod(path_str, mode)

    def stat(self, path: PurePath) -> os.stat_result:
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        sftp_attributes: paramiko.SFTPAttributes = self._inner_shell.stat(path_str)

        result = os.stat_result(())
        result.st_atime = (
            sftp_attributes.st_atime if sftp_attributes.st_atime is not None else 0
        )
        result.st_gid = (
            sftp_attributes.st_gid if sftp_attributes.st_gid is not None else 0
        )
        result.st_mode = (
            sftp_attributes.st_mode if sftp_attributes.st_mode is not None else 0
        )
        result.st_mtime = (
            sftp_attributes.st_mtime if sftp_attributes.st_mtime is not None else 0
        )
        result.st_size = (
            sftp_attributes.st_size if sftp_attributes.st_size is not None else 0
        )
        result.st_uid = (
            sftp_attributes.st_uid if sftp_attributes.st_uid is not None else 0
        )
        return result

    def is_dir(self, path: PurePath) -> bool:
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.is_dir(path_str))

    def is_symlink(self, path: PurePath) -> bool:
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.is_symlink(path_str))

    def symlink(self, source: PurePath, destination: PurePath) -> None:
        self.initialize()
        assert self._inner_shell
        source_str = self._purepath_to_str(source)
        destination_str = self._purepath_to_str(destination)
        self._inner_shell.symlink(source_str, destination_str)

    def chown(self, path: PurePath, uid: int, gid: int) -> None:
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        self._inner_shell.chown(path_str, uid, gid)

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        self.mkdir(node_path.parent, parents=True, exist_ok=True)
        self.initialize()
        assert self._inner_shell
        local_path_str = self._purepath_to_str(local_path)
        node_path_str = self._purepath_to_str(node_path)
        self._inner_shell.put(
            local_path_str,
            node_path_str,
            create_directories=True,
            consistent=self.is_posix,
        )

    def copy_back(self, node_path: PurePath, local_path: PurePath) -> None:
        self.initialize()
        assert self._inner_shell
        node_path_str = self._purepath_to_str(node_path)
        local_path_str = self._purepath_to_str(local_path)
        self._inner_shell.get(
            node_path_str,
            local_path_str,
            consistent=self.is_posix,
        )

    def _purepath_to_str(
        self, path: Union[Path, PurePath, str]
    ) -> Union[Path, PurePath, str]:
        """
        spurplus doesn't support pure path, so it needs to convert.
        """
        if isinstance(path, PurePath):
            path = str(path)
        return path


class LocalShell(InitializableMixin):
    def __init__(self) -> None:
        super().__init__()
        self.is_remote = False
        self._inner_shell = spur.LocalShell()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if "win32" == sys.platform:
            self.is_posix = False
        else:
            self.is_posix = True

    def close(self) -> None:
        ...

    @property
    def is_connected(self) -> bool:
        # local shell is always available.
        return True

    def spawn(
        self,
        command: Sequence[str],
        update_env: Optional[Mapping[str, str]] = None,
        store_pid: bool = False,
        cwd: Optional[Union[str, Path]] = None,
        stdout: Any = None,
        stderr: Any = None,
        encoding: str = "utf-8",
        use_pty: bool = False,
        allow_error: bool = False,
    ) -> spur.local.LocalProcess:
        return self._inner_shell.spawn(
            command=command,
            update_env=update_env,
            store_pid=store_pid,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            encoding=encoding,
            use_pty=use_pty,
            allow_error=allow_error,
        )

    def mkdir(
        self,
        path: PurePath,
        mode: int = 0o777,
        parents: bool = True,
        exist_ok: bool = False,
    ) -> None:
        assert isinstance(path, Path), f"actual: {type(path)}"
        path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def exists(self, path: PurePath) -> bool:
        assert isinstance(path, Path), f"actual: {type(path)}"
        return path.exists()

    def remove(self, path: PurePath, recursive: bool = False) -> None:
        assert isinstance(path, Path), f"actual: {type(path)}"
        path.rmdir()

    def chmod(self, path: PurePath, mode: int) -> None:
        assert isinstance(path, Path), f"actual: {type(path)}"
        path.chmod(mode)

    def stat(self, path: PurePath) -> os.stat_result:
        assert isinstance(path, Path), f"actual: {type(path)}"
        return path.stat()

    def is_dir(self, path: PurePath) -> bool:
        assert isinstance(path, Path), f"actual: {type(path)}"
        return path.is_dir()

    def is_symlink(self, path: PurePath) -> bool:
        assert isinstance(path, Path), f"actual: {type(path)}"
        return path.is_symlink()

    def symlink(self, source: PurePath, destination: PurePath) -> None:
        assert isinstance(source, Path), f"actual: {type(source)}"
        assert isinstance(destination, Path), f"actual: {type(destination)}"
        source.symlink_to(destination)

    def chown(self, path: PurePath, uid: int, gid: int) -> None:
        assert isinstance(path, Path), f"actual: {type(path)}"
        shutil.chown(path, cast(str, uid), cast(str, gid))

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        self.mkdir(node_path.parent, parents=True, exist_ok=True)
        shutil.copy(local_path, node_path)

    def copy_back(self, node_path: PurePath, local_path: PurePath) -> None:
        self.copy(local_path=node_path, node_path=local_path)


Shell = Union[LocalShell, SshShell]
