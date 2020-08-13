from lisa.core.tool import Tool


class Echo(Tool):
    @property
    def command(self) -> str:
        command = "echo"
        if not self.node.is_linux:
            command = "cmd /c echo"
        return command

    @property
    def _is_installed_internal(self) -> bool:
        return True
