import pathlib
import re
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux
from lisa.util import LisaException


class Wget(Tool):
    __pattern_path = re.compile(
        r"([\w\W]*?) (-|File) ‘(?P<path>.+?)’ (saved|already there)"
    )

    @property
    def command(self) -> str:
        return "wget"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        linux_os: Linux = cast(Linux, self.node.os)
        linux_os.install_packages([self])
        return self._check_exists()

    def get(
        self, url: str, file_path: str = "", filename: str = "", overwrite: bool = True
    ) -> str:
        # create folder when it doesn't exist
        self.node.execute(f"mkdir -p {file_path}", shell=True)
        # combine download file path
        # TODO: support current lisa folder in pathlib.
        # So that here can use the corresponding path format.
        download_path = pathlib.PurePosixPath(f"{file_path}/{filename}")
        if overwrite:
            extra_param = " -nc "
        if filename:
            run_command = f" {url} {extra_param} -O {download_path}"
        else:
            run_command = f" {url} {extra_param} -P {download_path}"
        command_result = self.run(run_command, no_error_log=True, shell=True)
        matched_result = self.__pattern_path.match(command_result.stdout)
        if matched_result:
            download_file_path = matched_result.group("path")
        actual_file_path = self.node.execute(f"ls {download_file_path}", shell=True)
        if actual_file_path.exit_code != 0:
            raise LisaException(f"File {actual_file_path} doesn't exist.")
        return actual_file_path.stdout
