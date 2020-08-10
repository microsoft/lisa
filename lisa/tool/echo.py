from lisa.core.tool import Tool


class Echo(Tool):
    @property
    def command(self) -> str:
        return "echo"

    def canInstall(self) -> bool:
        return False

    def installed(self) -> bool:
        return True
