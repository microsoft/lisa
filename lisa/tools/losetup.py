from lisa.executable import Tool


class Losetup(Tool):
    @property
    def command(self) -> str:
        return "losetup"

    @property
    def can_install(self) -> bool:
        return True

    def list(self) -> str:
        result = self.node.execute("losetup -a", sudo=True)
        return result.stdout

    def attach(self, image_path: str) -> str:
        result = self.node.execute(f"losetup -f --show {image_path}", sudo=True)
        return result.stdout.strip()

    def detach(self, loop_device: str) -> None:
        self.node.execute(f"losetup -d {loop_device}", sudo=True, expected_exit_code=0)

    def _install(self) -> bool:
        self.node.os.install_packages("util-linux")
        return self._check_exists()
