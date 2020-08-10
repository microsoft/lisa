from lisa.core.tool import Tool


class Echo(Tool):
    @property
    def command(self) -> str:
        command = "echo"
        if not self.node.isLinux:
            command = "cmd /c echo"
        return command

    @property
    def canInstall(self) -> bool:
        return False

    @property
    def isInstalledInternal(self) -> bool:
        return True
