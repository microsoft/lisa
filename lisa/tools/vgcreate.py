from lisa.executable import Tool


class Vgcreate(Tool):
    @property
    def command(self) -> str:
        return "vgcreate"

    @property
    def can_install(self) -> bool:
        return True

    def create_vg(self, vg_name: str, *devices: str) -> None:
        self.node.execute(f"vgcreate {vg_name} {' '.join(devices)}", sudo=True, expected_exit_code=0)

    def _install(self) -> bool:
        self.node.os.install_packages("lvm2")
        return self._check_exists()
