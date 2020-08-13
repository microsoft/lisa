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
        dependencies: Optional[List[Type[Tool]]] = None,
    ) -> None:
        super().__init__(node)
        self._local_path = local_path
        self._files = files
        self._cwd: Union[pathlib.PurePath, pathlib.Path]

        self._name = name
        self._command = command

        if dependencies:
            self._dependencies = dependencies
        else:
            self._dependencies = []

    def runasync(
        self,
        parameters: str = "",
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        if cwd is not None:
            raise LisaException("don't set cwd for script")
        if parameters:
            command = f"{self.command} {parameters}"
        else:
            command = self.command

        return self.node.executeasync(
            cmd=command,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=self._cwd,
        )

    def run(
        self,
        parameters: str = "",
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        process = self.runasync(
            parameters=parameters,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result()

    @property
    def name(self) -> str:
        return self._name

    @property
    def command(self) -> str:
        assert self._command
        return self._command

    @property
    def can_install(self) -> bool:
        return True

    @property
    def _is_installed_internal(self) -> bool:
        # the underlying 'isInstalledInternal' doesn't work for script
        # but once it's cached in node, it won't be copied again.
        return False

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return self._dependencies

    def install(self) -> bool:
        if self.node.is_remote:
            # copy to remote
            remote_root_path = self.node.get_tool_path(self)
            for file in self._files:
                remote_path = remote_root_path.joinpath(file)
                source_path = self._local_path.joinpath(file)
                self.node.shell.copy(source_path, remote_path)
                self.node.shell.chmod(remote_path, 0o755)
            self._cwd = remote_root_path
        else:
            self._cwd = self._local_path

        if not self._command:
            if self.node.is_linux:
                # in Linux, local script must to relative path.
                self._command = f"./{pathlib.PurePosixPath(self._files[0])}"
            else:
                # windows needs absolute path
                self._command = f"{self._cwd.joinpath(self._files[0])}"
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

        self._dependencies = dependencies

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

        self._files = files_path
        self._local_rootpath: pathlib.Path = root_path

        self._command: Union[str, None] = None
        if command:
            command_identifier = command
            self._command = command
        else:
            command_identifier = files[0]

        # generate an unique name based on file names
        command_identifier = self._normalize_pattern.sub("_", command_identifier)
        hash_source = "".join(files).encode("utf-8")
        hash_result = sha256(hash_source)
        self.name = f"custom_{command_identifier}_{hash_result.hexdigest()}"

    def build(self, node: Node) -> CustomScript:
        script = CustomScript(
            self.name, node, self._local_rootpath, self._files, self._command
        )
        script.initialize()
        return script
