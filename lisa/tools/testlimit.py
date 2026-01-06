from typing import Any, List, Optional, Type

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import Windows
from lisa.tools.unzip import Unzip
from lisa.util import LisaException


class TestLimit(Tool):
    _DOWNLOAD_URL = "https://download.sysinternals.com/files/Testlimit.zip"
    _ARCHIVE_NAME = "Testlimit.zip"
    _BINARY_NAMES = ["testlimit64.exe", "testlimit.exe"]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._binary_path: Optional[str] = None

    @property
    def command(self) -> str:
        if not self._binary_path and not self._check_exists():
            if not self.install() or not self._check_exists():
                raise LisaException("TestLimit binary is not available after install")

        if self._binary_path:
            return self._binary_path
        raise LisaException("TestLimit binary path could not be resolved")

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Wget, Unzip]

    def _install(self) -> bool:
        assert isinstance(
            self.node.os, Windows
        ), "TestLimit is supported on Windows only."

        tool_path = self.get_tool_path()
        archive_path = tool_path / self._ARCHIVE_NAME

        archive_path_str = self.node.get_str_path(archive_path)
        tool_path_str = self.node.get_str_path(tool_path)

        self.node.tools[Wget].get(
            url=self._DOWNLOAD_URL,
            file_path=tool_path_str,
            filename=self._ARCHIVE_NAME,
            overwrite=True,
            force_run=True,
        )

        self.node.tools[Unzip].extract(file=archive_path_str, dest_dir=tool_path_str)
        return self._check_exists()

    def _check_exists(self) -> bool:
        assert isinstance(
            self.node.os, Windows
        ), "TestLimit is supported on Windows only."

        tool_path = self.get_tool_path()
        for binary_name in self._BINARY_NAMES:
            candidate_path = tool_path / binary_name
            if self.node.shell.exists(candidate_path):
                self._binary_path = self.node.get_str_path(candidate_path)
                return True
        return False
