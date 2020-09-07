from typing import List, Type

from lisa.executable import Tool
from lisa.tools import Git
from lisa.util.process import ExecutableResult


class Ntttcp(Tool):
    repo = "https://github.com/microsoft/ntttcp-for-linux"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git]

    @property
    def command(self) -> str:
        return "ntttcp"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        tool_path = self.get_tool_path()
        self.node.shell.mkdir(tool_path, exist_ok=True)
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        code_path = tool_path.joinpath("ntttcp-for-linux/src")
        self.node.execute("make && sudo make install", shell=True, cwd=code_path)
        return self._check_exists()

    def help(self) -> ExecutableResult:
        return self.run("-h")
