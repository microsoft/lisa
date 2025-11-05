from lisa.tools import Tool

class Vgcreate(Tool):
    @property
    def command(self) -> str:
        return "vgcreate"

    def create(self, vg_name: str, *devices: str) -> None:
        args = " ".join([vg_name] + list(devices))
        self.run(args, sudo=True, expected_exit_code=0)

    def _is_installed(self) -> bool:
        return self._check_exists()

    def _install(self) -> bool:
        return self._install_package("lvm2")
