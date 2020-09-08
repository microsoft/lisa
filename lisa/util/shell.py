import logging
import os
import shutil
import sys
from functools import partial
from logging import getLogger
from pathlib import Path, PurePath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union, cast

import paramiko  # type: ignore
import spur  # type: ignore
import spurplus  # type: ignore

from lisa.util import LisaException
from lisa.util.logger import get_logger

_get_logger = partial(get_logger, "shell")


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
                "at least one of password and privateKeyFile need to be set"
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


class WindowsShellType(object):
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
            commands += f"{'; '.join(update_env_commands)}; "

        if cwd is not None:
            commands.append(f"pushd {cwd} & ")
            commands.append(" ".join(command_args))
            commands.append(" & popd")
        else:
            commands.append(" ".join(command_args))
        result = " ".join(commands)

        log = _get_logger()
        log.debug(f"command: {result}")

        return result


class SshShell:
    def __init__(self, connection_info: ConnectionInfo) -> None:
        self.is_remote = True
        self._is_initialized = False
        self._connection_info = connection_info
        self._inner_shell: Optional[spur.SshShell] = None

        self._log = _get_logger()
        paramiko_logger = getLogger("paramiko")
        paramiko_logger.setLevel(logging.WARN)

    def initialize(self) -> None:
        paramiko_client = paramiko.SSHClient()
        paramiko_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        paramiko_client.connect(
            hostname=self._connection_info.address,
            port=self._connection_info.port,
            password=self._connection_info.password,
            key_filename=self._connection_info.private_key_file,
        )
        spur_kwargs = {
            "hostname": self._connection_info.address,
            "username": self._connection_info.username,
            "password": self._connection_info.password,
            "port": self._connection_info.port,
            "private_key_file": self._connection_info.private_key_file,
            "missing_host_key": spur.ssh.MissingHostKey.accept,
            "connect_timeout": 10,
        }

        _, stdout, _ = paramiko_client.exec_command("cmd")
        stdout_content = stdout.read().decode("utf-8")
        if stdout_content and "Windows" in stdout_content:
            self.is_linux = False
            spur_ssh_shell = spur.SshShell(shell_type=WindowsShellType(), **spur_kwargs)
            sftp = spurplus.sftp.ReconnectingSFTP(
                sftp_opener=spur_ssh_shell._open_sftp_client
            )
            self._inner_shell = spurplus.SshShell(
                spur_ssh_shell=spur_ssh_shell, sftp=sftp
            )
        else:
            self.is_linux = True
            self._inner_shell = spurplus.connect_with_retries(**spur_kwargs)

    def close(self) -> None:
        if self._inner_shell:
            self._inner_shell.close()

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
        allow_error: bool = True,
    ) -> Any:
        assert self._inner_shell
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
        path_str = self._purepath_to_str(path)
        assert self._inner_shell
        self._inner_shell.mkdir(path_str, mode=mode, parents=parents, exist_ok=exist_ok)

    def exists(self, path: PurePath) -> bool:
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.exists(path_str))

    def remove(self, path: PurePath, recursive: bool = False) -> None:
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        self._inner_shell.remove(path_str, recursive)

    def chmod(self, path: PurePath, mode: int) -> None:
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        self._inner_shell.chmod(path_str, mode)

    def stat(self, path: PurePath) -> os.stat_result:
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        sftp_attributes: paramiko.SFTPAttributes = self._inner_shell.stat(path_str)

        result = os.stat_result(sftp_attributes.st_mode)
        result.st_mode = sftp_attributes.st_mode
        result.st_size = sftp_attributes.st_size
        result.st_uid = sftp_attributes.st_uid
        result.st_gid = sftp_attributes.st_gid
        result.st_atime = sftp_attributes.st_atime
        result.st_mtime = sftp_attributes.st_mtime
        return result

    def is_dir(self, path: PurePath) -> bool:
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.is_dir(path_str))

    def is_symlink(self, path: PurePath) -> bool:
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.is_symlink(path_str))

    def symlink(self, source: PurePath, destination: PurePath) -> None:
        assert self._inner_shell
        source_str = self._purepath_to_str(source)
        destination_str = self._purepath_to_str(destination)
        self._inner_shell.symlink(source_str, destination_str)

    def chown(self, path: PurePath, uid: int, gid: int) -> None:
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        self._inner_shell.chown(path_str, uid, gid)

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        self.mkdir(node_path.parent, parents=True, exist_ok=True)
        assert self._inner_shell
        local_path_str = self._purepath_to_str(local_path)
        node_path_str = self._purepath_to_str(node_path)
        self._inner_shell.put(local_path_str, node_path_str, create_directories=True)

    def _purepath_to_str(
        self, path: Union[Path, PurePath, str]
    ) -> Union[Path, PurePath, str]:
        """
        spurplus doesn't support pure path, so it needs to convert.
        """
        if isinstance(path, PurePath):
            path = str(path)
        return path


class LocalShell:
    def __init__(self) -> None:
        super().__init__()
        self.is_remote = False
        self._inner_shell = spur.LocalShell()

    def initialize(self) -> None:
        if "win32" == sys.platform:
            self.is_linux = False
        else:
            self.is_linux = True

    def close(self) -> None:
        pass

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
    ) -> Any:
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
        assert isinstance(path, Path)
        path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def exists(self, path: PurePath) -> bool:
        assert isinstance(path, Path)
        return path.exists()

    def remove(self, path: PurePath, recursive: bool = False) -> None:
        assert isinstance(path, Path)
        path.rmdir()

    def chmod(self, path: PurePath, mode: int) -> None:
        assert isinstance(path, Path)
        path.chmod(mode)

    def stat(self, path: PurePath) -> os.stat_result:
        assert isinstance(path, Path)
        return path.stat()

    def is_dir(self, path: PurePath) -> bool:
        assert isinstance(path, Path)
        return path.is_dir()

    def is_symlink(self, path: PurePath) -> bool:
        assert isinstance(path, Path)
        return path.is_symlink()

    def symlink(self, source: PurePath, destination: PurePath) -> None:
        assert isinstance(source, Path)
        assert isinstance(destination, Path)
        source.symlink_to(destination)

    def chown(self, path: PurePath, uid: int, gid: int) -> None:
        assert isinstance(path, Path)
        shutil.chown(path, cast(str, uid), cast(str, gid))

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        self.mkdir(node_path.parent, parents=True, exist_ok=True)
        assert isinstance(local_path, Path)
        assert isinstance(node_path, Path)
        shutil.copy(local_path, node_path)


Shell = Union[LocalShell, SshShell]
