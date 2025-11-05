from lisa.tools import Tool

class Losetup(Tool):
    @property
    def command(self) -> str:
        return "losetup"

    def list(self) -> str:
        result = self.run("-a", sudo=True)
        return result.stdout

    def attach(self, image_path: str) -> str:
        result = self.run(f"-f --show {image_path}", sudo=True)
        return result.stdout.strip()

    def detach(self, loop_device: str) -> None:
        self.run(f"-d {loop_device}", sudo=True, expected_exit_code=0)

    def _is_installed(self) -> bool:
        return self._check_exists()

    def _install(self) -> bool:
        return self._install_package("util-linux")
