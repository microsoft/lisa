import re
from typing import List, Type

from lisa.executable import Tool
from lisa.tools import Git, Make
from lisa.util.process import ExecutableResult


class Ntttcp(Tool):
    repo = "https://github.com/microsoft/ntttcp-for-linux"
    throughput_pattern = re.compile(r" 	 throughput	:(.+)")

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make]

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
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("ntttcp-for-linux/src")
        make.make_and_install(cwd=code_path)
        return self._check_exists()

    def help(self) -> ExecutableResult:
        return self.run("-h")

    def get_throughput(self, stdout: str) -> str:
        throughput = self.throughput_pattern.findall(stdout)
        if throughput:
            result: str = throughput[0]
        else:
            result = "cannot find throughput"
        return result
