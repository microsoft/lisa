from lisa.core.executable import Executable


class Echo(Executable):
    @property
    def command(self) -> str:
        return "echo"

    def canInstall(self) -> bool:
        return False

    def installed(self) -> bool:
        return True
