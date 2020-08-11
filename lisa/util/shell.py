from pathlib import Path
from typing import Optional, Union

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
