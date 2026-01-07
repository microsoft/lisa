from typing import Any, List, Type

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import Windows
from lisa.tools.powershell import PowerShell
from lisa.tools.unzip import Unzip


class TestLimit(Tool):
    _DOWNLOAD_URL = "https://download.sysinternals.com/files/Testlimit.zip"
    _ARCHIVE_NAME = "Testlimit.zip"
    _BINARY_NAME = "Testlimit64.exe"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._tool_path = self.get_tool_path()
        self._command = self._tool_path / self._BINARY_NAME

    @property
    def command(self) -> str:
        return str(self._command)

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Windows)

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Wget, Unzip]

    def _install(self) -> bool:
        archive_path = self._tool_path / self._ARCHIVE_NAME

        archive_path_str = str(archive_path)
        tool_path_str = str(self._tool_path)

        self.node.tools[Wget].get(
            url=self._DOWNLOAD_URL,
            file_path=tool_path_str,
            filename=self._ARCHIVE_NAME,
            overwrite=True,
            force_run=True,
        )
        self.node.tools[Unzip].extract(file=archive_path_str, dest_dir=tool_path_str)
        return self._check_exists()

    def apply_memory_pressure(self, memory_mb: int, duration: int) -> None:
        hv_pressure_exe = self.command
        ps_command = (
            f"$p = Start-Process -FilePath '{hv_pressure_exe}' "
            f"-ArgumentList '-accepteula -d {memory_mb}' -PassThru; "
            f"Start-Sleep -Seconds {duration}; "
            "if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force }"
        )
        self.node.tools[PowerShell].run_cmdlet(
            ps_command,
            force_run=True,
            no_debug_log=True,
        )
