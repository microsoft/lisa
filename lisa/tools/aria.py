from typing import Optional

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools.lscpu import Lscpu
from lisa.tools.make import Make
from lisa.tools.mkdir import Mkdir
from lisa.tools.tar import Tar
from lisa.util import ReleaseEndOfLifeException, RepoNotExistException


class Aria(Tool):
    _DOWNLOAD_LOCATION = "https://github.com/q3aql/aria2-static-builds/releases/download/v1.35.0/aria2-1.35.0-linux-gnu-64bit-build1.tar.bz2"  # noqa: E501
    _DOWNLOAD_TAR_NAME = "aria2-1.35.0-linux-gnu-64bit-build1.tar.bz2"
    _DOWNLOAD_NAME = "aria2-1.35.0-linux-gnu-64bit-build1"

    @property
    def command(self) -> str:
        return "aria2c"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        try:
            posix_os.install_packages(["aria2"])
        except (RepoNotExistException, ReleaseEndOfLifeException) as e:
            raise e
        except Exception as e:
            self._log.debug(f"Failed to install aria2: {e}")

        if not self._check_exists():
            self._log.debug("Installing aria2 from source")
            downloaded_file_path = self.node.tools[Wget].get(
                self._DOWNLOAD_LOCATION,
                file_path=str(self.node.working_path),
                filename=self._DOWNLOAD_TAR_NAME,
                force_run=True,
            )
            self.node.tools[Tar].extract(
                file=downloaded_file_path, dest_dir=str(self.node.working_path)
            )

            # make and install aria2
            self.node.tools[Make].make_install(
                cwd=self.node.working_path / self._DOWNLOAD_NAME
            )

        return self._check_exists()

    def get(
        self,
        url: str,
        file_path: str = "",
        filename: str = "",
        overwrite: bool = True,
        sudo: bool = False,
        force_run: bool = False,
        num_connections: Optional[int] = None,
        timeout: int = 600,
    ) -> str:
        if file_path:
            # create folder when it doesn't exist
            self.node.tools[Mkdir].create_directory(file_path, sudo=sudo)
        else:
            file_path = str(self.node.working_path)

        # set download path
        download_path = f"{file_path}/{filename}"

        # if num_connections is not specified, set to minimum of number of cores
        # on the node, or 16 which is the max number of connections aria2 can
        # handle
        if not num_connections:
            num_connections = min(self.node.tools[Lscpu].get_thread_count(), 16)

        # setup aria2c command and run
        command = f"-x {num_connections} --dir={file_path} --out={filename} "
        if overwrite:
            command += "--allow-overwrite=true "
            force_run = True
        command += f"'{url}'"
        self.run(
            command,
            sudo=sudo,
            force_run=force_run,
            timeout=timeout,
        )

        return download_path
