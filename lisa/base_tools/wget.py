import re
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Type
from urllib.parse import urlparse

from retry import retry

from lisa.base_tools import Cat
from lisa.executable import Tool
from lisa.tools.ls import Ls
from lisa.tools.mkdir import Mkdir
from lisa.tools.powershell import PowerShell
from lisa.tools.rm import Rm
from lisa.util import LisaException, LisaTimeoutException, is_valid_url

if TYPE_CHECKING:
    from lisa.operating_system import Posix


class Wget(Tool):
    # Saving '/home/username/lisa_working/20240323/20240323-070329-867/kvp_client'
    __pattern_path = re.compile(r"([\w\W]*?)Saving.*(‘|')(?P<path>.+?)(’|')")

    @property
    def command(self) -> str:
        return "wget"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._url_file_cache: Dict[str, str] = dict()
        super()._initialize(*args, **kwargs)

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages([self])
        return self._check_exists()

    @retry(LisaException, tries=5, delay=2, backoff=1.5)  # type: ignore
    def get(
        self,
        url: str,
        file_path: str = "",
        filename: str = "",
        overwrite: bool = True,
        executable: bool = False,
        sudo: bool = False,
        force_run: bool = False,
        timeout: int = 600,
    ) -> str:
        cached_filename = self._url_file_cache.get(url, None)
        if cached_filename:
            if force_run:
                del self._url_file_cache[url]
            else:
                return cached_filename

        is_valid_url(url)

        if not filename:
            filename = urlparse(url).path.split("/")[-1]
            self._log.debug(f"filename is not provided, use {filename} from url.")

        file_path, download_path = self._ensure_download_path(file_path, filename)

        # remove existing file and dir to download again.
        download_pure_path = self.node.get_pure_path(download_path)
        if overwrite and self.node.shell.exists(download_pure_path):
            self.node.shell.remove(download_pure_path, recursive=True)
            force_run = True
        command = f"'{url}' --no-check-certificate"
        if filename:
            command = f"{command} -O {download_path}"
        else:
            command = f"{command} -P {download_path}"
        # in some distro, the output is truncated, so we need to save it to a file.
        log_file = "wget_temp.log"
        command = f"{command} -o {log_file}"
        command_result = self.run(
            command,
            no_error_log=True,
            shell=True,
            sudo=sudo,
            force_run=force_run,
            timeout=timeout,
        )

        ls = self.node.tools[Ls]
        if ls.path_exists(log_file, sudo=sudo):
            temp_log = self.node.tools[Cat].read(log_file, sudo=sudo, force_run=True)
            matched_result = self.__pattern_path.match(temp_log)
            if matched_result:
                download_file_path = matched_result.group("path")
            else:
                self.node.tools[Rm].remove_file(log_file, sudo=sudo)
                raise LisaException(
                    f"cannot find file path in stdout of '{command}', it may be caused "
                    " due to failed download or pattern mismatch."
                    f" stdout: {command_result.stdout}"
                    f" templog: {temp_log}"
                )
            self.node.tools[Rm].remove_file(log_file, sudo=sudo)
        else:
            download_file_path = download_path

        if command_result.is_timeout:
            raise LisaTimeoutException(
                f"wget command is timed out after {timeout} seconds."
            )
        ls_result = self.node.execute(
            f"ls {download_file_path}",
            shell=True,
            sudo=sudo,
            expected_exit_code=0,
            expected_exit_code_failure_message="File path does not exist, "
            f"{download_file_path}",
        )
        actual_file_path = ls_result.stdout.strip()
        self._url_file_cache[url] = actual_file_path
        if executable:
            self.node.execute(f"chmod +x {actual_file_path}", sudo=sudo)
        return actual_file_path

    def verify_internet_access(self) -> bool:
        try:
            result = self.get("https://www.azure.com", force_run=True)
            if result:
                return True
        except Exception as e:
            self._log.debug(
                f"Internet is not accessible, exception occurred with wget {e}"
            )
        return False

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsWget

    def _ensure_download_path(self, path: str, filename: str) -> Tuple[str, str]:
        # combine download file path
        # TODO: support current lisa folder in pathlib.
        # So that here can use the corresponding path format.
        if path:
            # create folder when it doesn't exist
            self.node.shell.mkdir(self.node.get_pure_path(path), exist_ok=True)
            download_path = f"{path}/{filename}"
        else:
            path = self.node.get_str_path(self.node.working_path)
            download_path = f"{self.node.working_path}/{filename}"

        download_path = self.node.get_str_path(download_path)

        return path, download_path


class WindowsWget(Wget):
    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    def get(
        self,
        url: str,
        file_path: str = "",
        filename: str = "",
        overwrite: bool = True,
        executable: bool = False,
        sudo: bool = False,
        force_run: bool = False,
        timeout: int = 600,
    ) -> str:
        cached_filename = self._url_file_cache.get(url, None)
        if cached_filename:
            if force_run:
                del self._url_file_cache[url]
            else:
                return cached_filename

        ls = self.node.tools[Ls]

        if not filename:
            filename = urlparse(url).path.split("/")[-1]
            self._log.debug(f"filename is not provided, use {filename} from url.")

        file_path, download_path = self._ensure_download_path(file_path, filename)

        # return if file exists and not overwrite
        if ls.path_exists(file_path, sudo=sudo) and not overwrite:
            self._log.debug(
                f"File {download_path} already exists and rewrite is set to False"
            )

        # create directory if it doesn't exist
        self.node.tools[Mkdir].create_directory(file_path, sudo=sudo)

        # TODO: add support for executables
        # remove existing file if present and download
        self.node.tools[Rm].remove_file(download_path, sudo=sudo)
        self.node.tools[PowerShell].run_cmdlet(
            f"$ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri '{url}'"
            f" -OutFile '{download_path}'",
            sudo=sudo,
            force_run=force_run,
            timeout=timeout,
        )
        self._url_file_cache[url] = download_path
        return download_path
