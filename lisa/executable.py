# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, TypeVar, Union, cast

from lisa.util import InitializableMixin, LisaException, constants
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer
from lisa.util.process import ExecutableResult, Process

if TYPE_CHECKING:
    from lisa.node import Node


T = TypeVar("T")


class Tool(ABC, InitializableMixin):
    """
    The base class, which wraps an executable, package, or scripts on a node.
    A tool can be installed, and execute on a node. When a tool is needed, call
    Tools[] to get one object. The Tools[] checks if it's installed. If it's
    not installed, then check if it can be installed, and then install or fail.
    After the tool instance returned, the run/Async of the tool will call
    execute/Async of node. So that the command passes to current node.

    The must be implemented methods are marked with @abstractmethod, includes
    command: it's the command name, like echo, ntttcp. it uses in run/Async to run it,
             and isInstalledInternal to check if it's installed.

    The should be implemented methods throws NotImplementedError, but not marked as
    abstract method, includes,
    can_install: specify if a tool can be installed or not. If a tool is not builtin, it
                must implement this method.
    _install: If a tool is not builtin, it must implement this method. This
                     method needs to install a tool, and make sure it can be detected
                     by isInstalledInternal.

    The may be implemented methods is empty, includes
    initialize: It's called when a tool is created, and before to call any other
                methods. It can be used to initialize variables or time-costing
                operations.
    dependencies: All depended tools, they will be checked and installed before
                  current tool installed. For example, ntttcp uses git to clone code
                  and build. So it depends on Git tool.

    See details on method descriptions.
    """

    def __init__(self, node: Node) -> None:
        """
        It's not recommended to replace this __init__ method. Anything need to be
        initialized, should be in initialize() method.
        """
        super().__init__()
        self.node: Node = node
        # triple states, None means not checked.
        self._exists: Optional[bool] = None
        self._log = get_logger("tool", self.name, self.node.log)

    @property
    @abstractmethod
    def command(self) -> str:
        """
        Return command string, which can be run in console. For example, echo.
        The command can be different under different conditions. For example,
        package management is 'yum' on CentOS, but 'apt' on Ubuntu.
        """
        raise NotImplementedError()

    @property
    def can_install(self) -> bool:
        """
        Indicates if the tool supports installation or not. If it can return true,
        installInternal must be implemented.
        """
        raise NotImplementedError()

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        """
        return a windows version tool class, if it's needed
        """
        return None

    @property
    def package_name(self) -> str:
        """
        return package name,
        it may be different with command or different platform.
        """
        return self.command

    @classmethod
    def create(cls, node: Node) -> Tool:
        """
        if there is a windows version tool, return the windows instance.
        override this method if richer creation factory is needed.
        """
        tool_cls = cls
        if not node.is_linux:
            windows_tool = cls._windows_tool()
            if windows_tool:
                tool_cls = windows_tool
        return tool_cls(node)

    def _install(self) -> bool:
        """
        Execute installation process like build, install from packages. If other tools
        are depended, specify them in dependencies. Other tools can be used here,
        refer to ntttcp implementation.
        """
        raise NotImplementedError()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        Declare and initialize variables here, or some time costing initialization.
        This method is called before other methods, when initialing on a node.
        """
        pass

    @property
    def dependencies(self) -> List[Type[Tool]]:
        """
        Declare all dependencies here, it can be other tools, but prevent to be a
        circle dependency. The depdendented tools are checked and installed firstly.
        """
        return []

    @property
    def name(self) -> str:
        """
        Unique name to a tool and used as path of tool. Don't change it, or there may
        be unpredictable behavior.
        """
        return self.__class__.__name__.lower()

    def _check_exists(self) -> bool:
        """
        Default implementation to check if a tool exists. This method is called by
        isInstalled, and cached result. Builtin tools can override it can return True
        directly to save time.
        """
        if self.node.is_linux:
            where_command = "command -v"
        else:
            where_command = "where"
        result = self.node.execute(
            f"{where_command} {self.command}", shell=True, no_info_log=True
        )
        self._exists = result.exit_code == 0
        return self._exists

    @property
    def exists(self) -> bool:
        """
        Return if a tool installed. In most cases, overriding inInstalledInternal is
        enough. But if want to disable cached result and check tool every time,
        override this method. Notice, remote operations take times, that why caching is
        necessary.
        """
        # the check may need extra cost, so cache it's result.
        if self._exists is None:
            self._exists = self._check_exists()
        return self._exists

    def install(self) -> bool:
        """
        Default behavior of install a tool, including dependencies. It doesn't need to
        be overridden.
        """
        # check dependencies
        if self.dependencies:
            self._log.info("installing dependencies")
        for dependency in self.dependencies:
            self.node.tools[dependency]
        return self._install()

    def run_async(
        self,
        parameters: str = "",
        shell: bool = False,
        sudo: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        """
        Run a command async and return the Process. The process is used for async, or
        kill directly.
        """
        if parameters:
            command = f"{self.command} {parameters}"
        else:
            command = self.command
        return self.node.execute_async(
            command,
            shell=shell,
            sudo=sudo,
            no_error_log=no_error_log,
            cwd=cwd,
            no_info_log=no_info_log,
        )

    def run(
        self,
        parameters: str = "",
        shell: bool = False,
        sudo: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        cwd: Optional[pathlib.PurePath] = None,
        timeout: int = 600,
    ) -> ExecutableResult:
        """
        Run a process and wait for result.
        """
        process = self.run_async(
            parameters=parameters,
            shell=shell,
            sudo=sudo,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result(timeout=timeout)

    def get_tool_path(self) -> pathlib.PurePath:
        """
        compose a path, if the tool need to be installed
        """
        return self.node.working_path.joinpath(constants.PATH_TOOL, self.name)

    def __call__(
        self,
        parameters: str = "",
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        return self.run(
            parameters=parameters,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )


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
        self._name = name
        self._command = command

        super().__init__(node)
        self._local_path = local_path
        self._files = files
        self._cwd: Union[pathlib.PurePath, pathlib.Path]

        if dependencies:
            self._dependencies = dependencies
        else:
            self._dependencies = []

    def run_async(
        self,
        parameters: str = "",
        shell: bool = False,
        sudo: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        if cwd is not None:
            raise LisaException("don't set cwd for script")
        if parameters:
            command = f"{self.command} {parameters}"
        else:
            command = self.command

        return self.node.execute_async(
            cmd=command,
            shell=shell,
            sudo=sudo,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=self._cwd,
        )

    def run(
        self,
        parameters: str = "",
        shell: bool = False,
        sudo: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        cwd: Optional[pathlib.PurePath] = None,
        timeout: int = 600,
    ) -> ExecutableResult:
        process = self.run_async(
            parameters=parameters,
            shell=shell,
            sudo=sudo,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result(timeout=timeout)

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

    def _check_exists(self) -> bool:
        # the underlying '_check_exists' doesn't work for script
        # but once it's cached in node, it won't be copied again.
        return False

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return self._dependencies

    def install(self) -> bool:
        if self.node.is_remote:
            # copy to remote
            node_script_path = self.get_tool_path()
            for file in self._files:
                remote_path = node_script_path.joinpath(file)
                source_path = self._local_path.joinpath(file)
                self.node.shell.copy(source_path, remote_path)
                self.node.shell.chmod(remote_path, 0o755)
            self._cwd = node_script_path
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
        command_identifier = constants.NORMALIZE_PATTERN.sub("_", command_identifier)
        hash_source = "".join(files).encode("utf-8")
        hash_result = sha256(hash_source)
        self.name = f"custom_{command_identifier}_{hash_result.hexdigest()}".lower()

    def build(self, node: Node) -> CustomScript:
        return CustomScript(
            self.name, node, self._local_rootpath, self._files, self._command
        )


class Tools:
    def __init__(self, node: Node) -> None:
        self._node = node
        self._cache: Dict[str, Tool] = dict()

    def __getattr__(self, key: str) -> Tool:
        """
        for shortcut access like node.tools.echo.call_method()
        """
        return self.__getitem__(key)

    def __getitem__(self, tool_type: Union[Type[T], CustomScriptBuilder, str]) -> T:
        """
        return a typed subclass of tool or script builder.

        for example,
        echo_tool = node.tools[Echo]
        echo_tool.run("hello")
        """
        if tool_type is CustomScriptBuilder:
            raise LisaException(
                "CustomScriptBuilder should call build to create a script instance"
            )
        if isinstance(tool_type, CustomScriptBuilder):
            tool_key = tool_type.name
        elif isinstance(tool_type, str):
            tool_key = tool_type.lower()
        else:
            tool_key = tool_type.__name__.lower()
        tool = self._cache.get(tool_key)
        if tool is None:
            # the Tool is not installed on current node, try to install it.
            tool_log = get_logger("tool", tool_key, self._node.log)
            tool_log.debug(f"initializing tool [{tool_key}]")

            if isinstance(tool_type, CustomScriptBuilder):
                tool = tool_type.build(self._node)
            elif isinstance(tool_type, str):
                raise LisaException(
                    f"{tool_type} cannot be found. "
                    f"short usage need to get with type before get with name."
                )
            else:
                cast_tool_type = cast(Type[Tool], tool_type)
                tool = cast_tool_type.create(self._node)

            tool.initialize()

            if not tool.exists:
                tool_log.debug(f"'{tool.name}' not installed")
                if tool.can_install:
                    tool_log.debug(f"{tool.name} is installing")
                    timer = create_timer()
                    is_success = tool.install()
                    if not is_success:
                        raise LisaException(
                            f"install '{tool.name}' failed. After installed, "
                            f"it cannot be detected."
                        )
                    tool_log.debug(f"installed in {timer}")
                else:
                    raise LisaException(
                        f"cannot find [{tool.name}] on [{self._node.name}], "
                        f"{self._node.os.__class__.__name__}, "
                        f"Remote({self._node.is_remote}) "
                        f"and installation of [{tool.name}] isn't enabled in lisa."
                    )
            else:
                tool_log.debug("installed already")
            self._cache[tool_key] = tool
        return cast(T, tool)
