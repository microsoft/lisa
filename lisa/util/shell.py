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
        self.isRemote = False
        self.innerShell: Optional[Union[spurplus.SshShell, spur.LocalShell]] = None
        self._isInitialized = False

    def setConnectionInfo(self, connectionInfo: ConnectionInfo) -> None:
        self.connectionInfo = connectionInfo
        self.isRemote = True

    def initialize(self) -> None:
        if not self._isInitialized:
            self._isInitialized = True
            if self.isRemote:
                assert self.connectionInfo
                self.innerShell = spurplus.connect_with_retries(
                    self.connectionInfo.address,
                    port=self.connectionInfo.port,
                    username=self.connectionInfo.username,
                    password=self.connectionInfo.password,
                    private_key_file=self.connectionInfo.privateKeyFile,
                    missing_host_key=spur.ssh.MissingHostKey.accept,
                )
            else:
                self.innerShell = spur.LocalShell()

    def close(self) -> None:
        if self.innerShell and isinstance(self.innerShell, spurplus.SshShell):
            self.innerShell.close()

    def mkdir(
        self,
        path: PurePath,
        mode: int = 0o777,
        parents: bool = True,
        exist_ok: bool = False,
    ) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            path_str = self._purePathToStr(path)
            self.innerShell.mkdir(
                path_str, mode=mode, parents=parents, exist_ok=exist_ok
            )
        else:
            assert isinstance(path, Path)
            path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def exists(self, path: PurePath) -> bool:
        self.initialize()
        exists = False
        if self.isRemote:
            assert self.innerShell
            path_str = self._purePathToStr(path)
            exists = self.innerShell.exists(path_str)
        else:
            assert isinstance(path, Path)
            exists = path.exists()
        return exists

    def remove(self, path: PurePath, recursive: bool = False) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            path_str = self._purePathToStr(path)
            self.innerShell.remove(path_str, recursive)
        else:
            assert isinstance(path, Path)
            path.rmdir()

    def chmod(self, path: PurePath, mode: int) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            path_str = self._purePathToStr(path)
            self.innerShell.chmod(path_str, mode)
        else:
            assert isinstance(path, Path)
            path.chmod(mode)

    def stat(self, path: PurePath) -> os.stat_result:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            path_str = self._purePathToStr(path)
            sftp_attributes: paramiko.SFTPAttributes = self.innerShell.stat(path_str)

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
        if self.isRemote:
            assert self.innerShell
            path_str = self._purePathToStr(path)
            result: bool = self.innerShell.is_dir(path_str)
        else:
            assert isinstance(path, Path)
            result = path.is_dir()
        return result

    def is_symlink(self, path: PurePath) -> bool:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            path_str = self._purePathToStr(path)
            result: bool = self.innerShell.is_symlink(path_str)
        else:
            assert isinstance(path, Path)
            result = path.is_symlink()
        return result

    def symlink(self, source: PurePath, destination: PurePath) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            source_str = self._purePathToStr(source)
            destination_str = self._purePathToStr(destination)
            self.innerShell.symlink(source_str, destination_str)
        else:
            assert isinstance(source, Path)
            assert isinstance(destination, Path)
            source.symlink_to(destination)

    def chown(self, path: PurePath, uid: int, gid: int) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            path_str = self._purePathToStr(path)
            self.innerShell.chown(path_str, uid, gid)
        else:
            assert isinstance(path, Path)
            shutil.chown(path, cast(str, uid), cast(str, gid))

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        self.initialize()
        self.mkdir(node_path.parent, parents=True, exist_ok=True)
        if self.isRemote:
            assert self.innerShell
            local_path_str = self._purePathToStr(local_path)
            node_path_str = self._purePathToStr(node_path)
            self.innerShell.put(local_path_str, node_path_str, create_directories=True)
        else:
            assert isinstance(local_path, Path)
            assert isinstance(node_path, Path)
            shutil.copy(local_path, node_path)

    def _purePathToStr(
        self, path: Union[Path, PurePath, str]
    ) -> Union[Path, PurePath, str]:
        """
        spurplus doesn't support pure path, so it needs to convert.
        """
        if isinstance(path, PurePath):
            path = str(path)
        return path
