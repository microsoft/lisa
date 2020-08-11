from __future__ import annotations

from hashlib import md5
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Type

from lisa.core.testSuite import TestSuite
from lisa.core.tool import Tool
from lisa.util.executableResult import ExecutableResult
from lisa.util.process import Process

if TYPE_CHECKING:
    from lisa.core.node import Node


class CustomScript:
    def __init__(self, node: Node, cwd: Path, command: str) -> None:
        self.node = node
        self.cwd = cwd
        self.command = command

    def runAsync(
        self,
        extraParameters: str = "",
        noErrorLog: bool = False,
        noInfoLog: bool = False,
    ) -> Process:
        command = f"{self.command} {extraParameters}"
        return self.node.executeAsync(
            cmd=command,
            useBash=True,
            noErrorLog=noErrorLog,
            noInfoLog=noInfoLog,
            cwd=self.cwd,
        )

    def run(
        self,
        extraParameters: str = "",
        noErrorLog: bool = False,
        noInfoLog: bool = False,
    ) -> ExecutableResult:
        process = self.runAsync(
            extraParameters=extraParameters, noErrorLog=noErrorLog, noInfoLog=noInfoLog,
        )
        return process.waitResult()


class CustomScriptSpec:
    def __init__(
        self,
        root_path: Path,
        files: List[str],
        command: Optional[str] = None,
        dependencies: List[Type[Tool]] = [],
    ) -> None:
        if not files:
            raise Exception("CustomScriptSpec should have at least one file")

        self.files = files
        self.dependencies = dependencies

        self._localRootPath: Path = root_path

        if command:
            self.command = command
        else:
            self.command = files[0]

        # generate an unique name for dict hash
        hash_source = "".join(files).encode("utf-8")
        hash_result = md5(hash_source)
        self.name = hash_result.hexdigest()

    def install(self, node: Node) -> CustomScript:
        assert self.files

        for dependency in self.dependencies:
            node.getTool(dependency)

        for file_str in self.files:
            file = self._localRootPath.joinpath(file_str)
            if not file.exists():
                raise Exception(f"cannot find file {file}")

        if node.isRemote:
            # copy to remote
            remote_root_path = node.getScriptPath()
            for file_str in self.files:
                remote_path = remote_root_path.joinpath(file_str)
                source_path = self._localRootPath.joinpath(file_str)
                node.shell.copy(source_path, remote_path)
                node.shell.chmod(remote_path, 0o755)
            cwd = remote_root_path
        else:
            cwd = self._localRootPath

        return CustomScript(node, cwd, self.command)
