from __future__ import annotations

import pathlib
import re
from hashlib import sha256
from typing import TYPE_CHECKING, List, Optional, Type, Union

from lisa.core.tool import Tool
from lisa.util.exceptions import LisaException
from lisa.util.executableResult import ExecutableResult
from lisa.util.process import Process

if TYPE_CHECKING:
    from lisa.core.node import Node


class CustomScript(Tool):
    def __init__(
        self,
        name: str,
        node: Node,
        local_path: pathlib.Path,
        files: List[pathlib.PurePath],
        command: Optional[str] = None,
    ) -> None:
        super().__init__(node)
        self.localPath = local_path
        self.files = files
        self.cwd: Union[pathlib.PurePath, pathlib.Path]

        self._name = name
        self._command = command

    def runAsync(
        self,
        extraParameters: str = "",
        shell: bool = False,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        if cwd is not None:
            raise LisaException("don't set cwd for script")
        if extraParameters:
            command = f"{self.command} {extraParameters}"
        else:
            command = self.command

        return self.node.executeAsync(
            cmd=command,
            shell=shell,
            noErrorLog=noErrorLog,
            noInfoLog=noInfoLog,
            cwd=self.cwd,
        )

    def run(
        self,
        extraParameters: str = "",
        shell: bool = False,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        process = self.runAsync(
            extraParameters=extraParameters,
            shell=shell,
            noErrorLog=noErrorLog,
            noInfoLog=noInfoLog,
            cwd=cwd,
        )
        return process.waitResult()

    @property
    def name(self) -> str:
        return self._name

    @property
    def command(self) -> str:
        assert self._command
        return self._command

    @property
    def canInstall(self) -> bool:
        return True

    @property
    def isInstalledInternal(self) -> bool:
        # the underlying 'isInstalledInternal' doesn't work for script
        # but once it's cached in node, it won't be copied again.
        return False

    def install(self) -> bool:
        if self.node.isRemote:
            # copy to remote
            remote_root_path = self.node.getToolPath(self)
            for file in self.files:
                remote_path = remote_root_path.joinpath(file)
                source_path = self.localPath.joinpath(file)
                self.node.shell.copy(source_path, remote_path)
                self.node.shell.chmod(remote_path, 0o755)
            self.cwd = remote_root_path
        else:
            self.cwd = self.localPath

        if not self._command:
            if self.node.isLinux:
                # in Linux, local script must to relative path.
                self._command = f"./{pathlib.PurePosixPath(self.files[0])}"
            else:
                # windows needs absolute path
                self._command = f"{self.cwd.joinpath(self.files[0])}"
        return True


class CustomScriptBuilder:
    """
        With CustomScriptBuilder, provides variables is enough to use like a tool
        It needs some special handling in tool.py, but not much.
    """

    _normalize_pattern = re.compile(r"[^\w]|\d")

    def __init__(
        self,
        root_path: pathlib.Path,
        files: List[str],
        command: Optional[str] = None,
        dependencies: Optional[List[Type[Tool]]] = None,
    ) -> None:
        if not files:
            raise LisaException("CustomScriptSpec should have at least one file")

        self.dependencies = dependencies

        root_path = root_path.resolve().absolute()
        files_path: List[pathlib.PurePath] = []

        for file_str in files:
            file = pathlib.PurePath(file_str)
            if not file.is_absolute:
                raise LisaException(f"file must be relative path: '{file_str}'")

            absolute_file = root_path.joinpath(file).resolve()
            if not absolute_file.exists():
                raise LisaException(f"cannot find file {absolute_file}")

            try:
                file = absolute_file.relative_to(root_path)
            except ValueError:
                raise LisaException(f"file '{file_str}' must be in '{root_path}'")
            files_path.append(file)

        self.files = files_path
        self._localRootPath: pathlib.Path = root_path

        self.command: Union[str, None] = None
        if command:
            command_identifier = command
            self.command = command
        else:
            command_identifier = files[0]

        # generate an unique name based on file names
        command_identifier = self._normalize_pattern.sub("_", command_identifier)
        hash_source = "".join(files).encode("utf-8")
        hash_result = sha256(hash_source)
        self.name = f"custom_{command_identifier}_{hash_result.hexdigest()}"

    def build(self, node: Node) -> CustomScript:
        return CustomScript(
            self.name, node, self._localRootPath, self.files, self.command
        )
