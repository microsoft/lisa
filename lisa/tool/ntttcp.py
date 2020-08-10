from typing import List, TypeVar

from lisa.core.tool import Tool
from lisa.tool import Git
from lisa.util.executableResult import ExecutableResult

T = TypeVar("T")


class Ntttcp(Tool):
    repo = "https://github.com/microsoft/ntttcp-for-linux"

    @property
    def dependentedTools(self) -> List[T]:
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
        self.node.execute(
            f"cd {code_path.as_posix()} && make && sudo make install", useBash=True
        )
        return self.isInstalledInternal

    def help(self) -> ExecutableResult:
        return self.run("-h")
