import pathlib
import re
from typing import TYPE_CHECKING

from lisa.executable import Tool
from lisa.util import LisaException

if TYPE_CHECKING:
    from lisa.operating_system import Posix


class Wget(Tool):
    __pattern_path = re.compile(
        r"([\w\W]*?)(-|File) (‘|')(?P<path>.+?)(’|') (saved|already there)"
    )

    # regex to validate url
    # source -
    # https://github.com/django/django/blob/stable/1.3.x/django/core/validators.py#L45
    __url_pattern = re.compile(
        r"^(?:http|ftp)s?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)"
        r"+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # ...domain
        r"localhost|"  # localhost...
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )

    @property
    def command(self) -> str:
        return "wget"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages([self])
        return self._check_exists()

    def get(
        self,
        url: str,
        file_path: str = "",
        filename: str = "",
        overwrite: bool = True,
        executable: bool = False,
    ) -> str:
        if re.match(self.__url_pattern, url) is None:
            raise LisaException(f"Invalid URL '{url}'")
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
        else:
            raise LisaException(
                f"cannot find file path in stdout of '{run_command}', it may cause by "
                f"download failed or pattern mismatch. stdout: {command_result.stdout}"
            )
        actual_file_path = self.node.execute(f"ls {download_file_path}", shell=True)
        if actual_file_path.exit_code != 0:
            raise LisaException(f"File {actual_file_path} doesn't exist.")
        if executable:
            self.node.execute(f"chmod +x {actual_file_path}")

        return actual_file_path.stdout
