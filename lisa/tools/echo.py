from lisa.executable import Tool


class Echo(Tool):
    @property
    def command(self) -> str:
        return "echo"

    @property
    def _is_installed_internal(self) -> bool:
        return True
