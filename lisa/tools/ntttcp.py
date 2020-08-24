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
        can_install = False
        if self.node.is_linux:
            can_install = True
        return can_install

    def _install_internal(self) -> bool:
        tool_path = self.get_tool_path()
        self.node.shell.mkdir(tool_path)
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        code_path = tool_path.joinpath("ntttcp-for-linux/src")
        self.node.execute("make && sudo make install", shell=True, cwd=code_path)
        return self._is_installed_internal

    def help(self) -> ExecutableResult:
        return self.run("-h")
