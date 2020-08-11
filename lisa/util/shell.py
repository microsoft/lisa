import os
import shutil
from pathlib import Path
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
        path: Path,
        mode: int = 0o777,
        parents: bool = True,
        exist_ok: bool = False,
    ) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            self.innerShell.mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)
        else:
            path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def exists(self, path: Path) -> bool:
        self.initialize()
        exists = False
        if self.isRemote:
            assert self.innerShell
            exists = self.innerShell.exists(path)
        else:
            exists = path.exists()
        return exists

    def remove(self, path: Path, recursive: bool = False) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            self.innerShell.remove(path, recursive)
        else:
            path.rmdir()

    def chmod(self, path: Path, mode: int) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            self.innerShell.chmod(path, mode)
        else:
            path.chmod(mode)

    def stat(self, path: Path) -> os.stat_result:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            sftp_attributes: paramiko.SFTPAttributes = self.innerShell.stat(path)

            result = os.stat_result(sftp_attributes.st_mode)
            result.st_mode = sftp_attributes.st_mode
            result.st_size = sftp_attributes.st_size
            result.st_uid = sftp_attributes.st_uid
            result.st_gid = sftp_attributes.st_gid
            result.st_atime = sftp_attributes.st_atime
            result.st_mtime = sftp_attributes.st_mtime
        else:
            result = path.stat()
        return result

    def is_dir(self, path: Path) -> bool:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            result: bool = self.innerShell.is_dir(path)
        else:
            result = path.is_dir()
        return result

    def is_symlink(self, path: Path) -> bool:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            result: bool = self.innerShell.is_symlink(path)
        else:
            result = path.is_symlink()
        return result

    def symlink(self, source: Path, destination: Path) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            self.innerShell.symlink(source, destination)
        else:
            source.symlink_to(destination)

    def chown(self, path: Path, uid: int, gid: int) -> None:
        self.initialize()
        if self.isRemote:
            assert self.innerShell
            self.innerShell.chown(path, uid, gid)
        else:
            shutil.chown(path, cast(str, uid), cast(str, gid))

    def copy(self, local_path: Path, node_path: Path) -> None:
        self.initialize()
        self.mkdir(node_path.parent)
        if self.isRemote:
            assert self.innerShell
            self.innerShell.put(local_path, node_path, create_directories=True)
        else:
            shutil.copy(local_path, node_path)
