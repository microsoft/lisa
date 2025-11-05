from lisa.tools import Tool

class Pvcreate(Tool):
    @property
    def command(self) -> str:
        return "pvcreate"

    def create(self, *devices: str) -> None:
        self.run(" ".join(devices), sudo=True, expected_exit_code=0)

    def _is_installed(self) -> bool:
        return self._check_exists()

    def _install(self) -> bool:
        return self._install_package("lvm2")
