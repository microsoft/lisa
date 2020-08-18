import os
import shutil
from pathlib import Path, PurePath
from typing import Any, Mapping, Optional, Sequence, Union, cast

import paramiko  # type: ignore
import spur  # type: ignore
import spurplus  # type: ignore

from lisa.util.exceptions import LisaException


class ConnectionInfo:
    def __init__(
        self,
        address: str = "",
        port: int = 22,
        username: str = "root",
        password: Optional[str] = "",
        privatekey_file: str = "",
    ) -> None:
        self.address = address
        self.port = port
        self.username = username
        self.password = password
        self.privatekey_file = privatekey_file

        if not self.password and not self.privatekey_file:
            raise LisaException(
                "at least one of password and privateKeyFile need to be set"
            )
        elif not self.privatekey_file:
            self._use_password = True
        else:
            if not Path(self.privatekey_file).exists():
                raise FileNotFoundError(self.privatekey_file)
            self.password = None
            self._use_password = False

        if not self.username:
            raise LisaException("username must be set")


class SshShell:
    def __init__(self, connection_info: ConnectionInfo) -> None:
        self.is_remote = True
        self._is_initialized = False
        self._connection_info = connection_info
        self._inner_shell: Optional[spurplus.SshShell] = None

    def initialize(self) -> None:
        self._inner_shell = spurplus.connect_with_retries(
            self._connection_info.address,
            port=self._connection_info.port,
            username=self._connection_info.username,
            password=self._connection_info.password,
            private_key_file=self._connection_info.privatekey_file,
            missing_host_key=spur.ssh.MissingHostKey.accept,
        )

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
        allow_error: bool = False,
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
        self.is_remote = False
        self._inner_shell = spur.LocalShell()

    def initialize(self) -> None:
        pass

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
