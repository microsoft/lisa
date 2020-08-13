import os
import shutil
from pathlib import Path, PurePath
from typing import Optional, Union, cast

import paramiko  # type: ignore
import spur  # type: ignore
import spurplus  # type: ignore

from lisa.util.connectionInfo import ConnectionInfo


class Shell:
    """
    this class wraps local and remote file operations with similar behavior.
    """

    def __init__(self) -> None:
        self.inner_shell: Optional[Union[spurplus.SshShell, spur.LocalShell]] = None
        self.is_remote = False

        self._is_initialized = False

    def set_connection_info(self, connection_info: ConnectionInfo) -> None:
        self._connection_info = connection_info
        self.is_remote = True

    def initialize(self) -> None:
        if not self._is_initialized:
            self._is_initialized = True
            if self.is_remote:
                assert self._connection_info
                self.inner_shell = spurplus.connect_with_retries(
                    self._connection_info.address,
                    port=self._connection_info.port,
                    username=self._connection_info.username,
                    password=self._connection_info.password,
                    private_key_file=self._connection_info.privatekey_file,
                    missing_host_key=spur.ssh.MissingHostKey.accept,
                )
            else:
                self.inner_shell = spur.LocalShell()

    def close(self) -> None:
        if self.inner_shell and isinstance(self.inner_shell, spurplus.SshShell):
            self.inner_shell.close()

    def mkdir(
        self,
        path: PurePath,
        mode: int = 0o777,
        parents: bool = True,
        exist_ok: bool = False,
    ) -> None:
        self.initialize()
        if self.is_remote:
            assert self.inner_shell
            path_str = self._purepath_to_str(path)
            self.inner_shell.mkdir(
                path_str, mode=mode, parents=parents, exist_ok=exist_ok
            )
        else:
            assert isinstance(path, Path)
            path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def exists(self, path: PurePath) -> bool:
        self.initialize()
        exists = False
        if self.is_remote:
            assert self.inner_shell
            path_str = self._purepath_to_str(path)
            exists = self.inner_shell.exists(path_str)
        else:
            assert isinstance(path, Path)
            exists = path.exists()
        return exists

    def remove(self, path: PurePath, recursive: bool = False) -> None:
        self.initialize()
        if self.is_remote:
            assert self.inner_shell
            path_str = self._purepath_to_str(path)
            self.inner_shell.remove(path_str, recursive)
        else:
            assert isinstance(path, Path)
            path.rmdir()

    def chmod(self, path: PurePath, mode: int) -> None:
        self.initialize()
        if self.is_remote:
            assert self.inner_shell
            path_str = self._purepath_to_str(path)
            self.inner_shell.chmod(path_str, mode)
        else:
            assert isinstance(path, Path)
            path.chmod(mode)

    def stat(self, path: PurePath) -> os.stat_result:
        self.initialize()
        if self.is_remote:
            assert self.inner_shell
            path_str = self._purepath_to_str(path)
            sftp_attributes: paramiko.SFTPAttributes = self.inner_shell.stat(path_str)

            result = os.stat_result(sftp_attributes.st_mode)
            result.st_mode = sftp_attributes.st_mode
            result.st_size = sftp_attributes.st_size
            result.st_uid = sftp_attributes.st_uid
            result.st_gid = sftp_attributes.st_gid
            result.st_atime = sftp_attributes.st_atime
            result.st_mtime = sftp_attributes.st_mtime
        else:
            assert isinstance(path, Path)
            result = path.stat()
        return result

    def is_dir(self, path: PurePath) -> bool:
        self.initialize()
        if self.is_remote:
            assert self.inner_shell
            path_str = self._purepath_to_str(path)
            result: bool = self.inner_shell.is_dir(path_str)
        else:
            assert isinstance(path, Path)
            result = path.is_dir()
        return result

    def is_symlink(self, path: PurePath) -> bool:
        self.initialize()
        if self.is_remote:
            assert self.inner_shell
            path_str = self._purepath_to_str(path)
            result: bool = self.inner_shell.is_symlink(path_str)
        else:
            assert isinstance(path, Path)
            result = path.is_symlink()
        return result

    def symlink(self, source: PurePath, destination: PurePath) -> None:
        self.initialize()
        if self.is_remote:
            assert self.inner_shell
            source_str = self._purepath_to_str(source)
            destination_str = self._purepath_to_str(destination)
            self.inner_shell.symlink(source_str, destination_str)
        else:
            assert isinstance(source, Path)
            assert isinstance(destination, Path)
            source.symlink_to(destination)

    def chown(self, path: PurePath, uid: int, gid: int) -> None:
        self.initialize()
        if self.is_remote:
            assert self.inner_shell
            path_str = self._purepath_to_str(path)
            self.inner_shell.chown(path_str, uid, gid)
        else:
            assert isinstance(path, Path)
            shutil.chown(path, cast(str, uid), cast(str, gid))

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        self.initialize()
        self.mkdir(node_path.parent, parents=True, exist_ok=True)
        if self.is_remote:
            assert self.inner_shell
            local_path_str = self._purepath_to_str(local_path)
            node_path_str = self._purepath_to_str(node_path)
            self.inner_shell.put(local_path_str, node_path_str, create_directories=True)
        else:
            assert isinstance(local_path, Path)
            assert isinstance(node_path, Path)
            shutil.copy(local_path, node_path)

    def _purepath_to_str(
        self, path: Union[Path, PurePath, str]
    ) -> Union[Path, PurePath, str]:
        """
        spurplus doesn't support pure path, so it needs to convert.
        """
        if isinstance(path, PurePath):
            path = str(path)
        return path
