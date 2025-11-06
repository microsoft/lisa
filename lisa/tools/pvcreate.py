from lisa.executable import Tool


class Pvcreate(Tool):
    @property
    def command(self) -> str:
        return "pvcreate"

    @property
    def can_install(self) -> bool:
        return True

    def create_pv(self, *devices: str) -> None:
        self.node.execute(
            f"pvcreate {' '.join(devices)}", sudo=True, expected_exit_code=0
        )

    def _install(self) -> bool:
        self.node.os.install_packages("lvm2")
        return self._check_exists()
