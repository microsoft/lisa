from lisa.tools import Tool

class Lvcreate(Tool):
    @property
    def command(self) -> str:
        return "lvcreate"

    def create(self, size: str, name: str, vg_name: str, device: str = None, extra: str = "") -> None:
        args = f"-L {size} -n {name} {vg_name}"
        if device:
            args += f" {device}"
        if extra:
            args += f" {extra}"
        self.run(args, sudo=True, expected_exit_code=0)

    def _is_installed(self) -> bool:
        return self._check_exists()

    def _install(self) -> bool:
        return self._install_package("lvm2")
