from typing import List, Type

from lisa.core.tool import Tool
from lisa.tool import Git
from lisa.util.executableResult import ExecutableResult


class Ntttcp(Tool):
    repo = "https://github.com/microsoft/ntttcp-for-linux"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git]

    @property
    def command(self) -> str:
        return "ntttcp"

    @property
    def canInstall(self) -> bool:
        can_install = False
        if self.node.isLinux:
            can_install = True
        return can_install

    def install(self) -> bool:
        tool_path = self.node.getToolPath(self)
        self.node.shell.mkdir(tool_path)
        git = self.node.getTool(Git)
        git.clone(self.repo, tool_path)
        code_path = tool_path.joinpath("ntttcp-for-linux/src")
        self.node.execute("make && sudo make install", shell=True, cwd=code_path)
        return self.isInstalledInternal

    def help(self) -> ExecutableResult:
        return self.run("-h")
