from typing import Optional, Type

from lisa.executable import Tool


class Echo(Tool):
    @property
    def command(self) -> str:
        return "echo"

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsEcho

    def _check_exists(self) -> bool:
        return True


class WindowsEcho(Echo):
    @property
    def command(self) -> str:
        return "cmd /c echo"
