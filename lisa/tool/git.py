import pathlib

from lisa.core.tool import Tool


class Git(Tool):
    @property
    def command(self) -> str:
        return "git"

    @property
    def can_install(self) -> bool:
        # TODO support installation later
        return False

    def clone(self, url: str, cwd: pathlib.PurePath) -> None:
        self.run(f"clone {url}", cwd=cwd)
