import pathlib

from lisa.executable import Tool


class Git(Tool):
    @property
    def command(self) -> str:
        return "git"

    @property
    def can_install(self) -> bool:
        # TODO support installation later
        return False

    def clone(self, url: str, cwd: pathlib.PurePath) -> None:
        # git print to stderr for normal info, so set no_error_log to True.
        self.run(f"clone {url}", cwd=cwd, no_error_log=True)
