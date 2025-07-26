# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import pathlib
from hashlib import sha256
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

from lisa.util import InitializableMixin, LisaException, constants
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer
from lisa.util.process import ExecutableResult, Process

if TYPE_CHECKING:
    from lisa.node import Node

T = TypeVar("T")


class Tool(InitializableMixin):
    """
    The base class, which wraps an executable, package, or scripts on a node. A
    tool can be installed, and execute on a node. When a tool is needed, call
    Tools[] to get one object. The Tools[] checks if it's installed. If it's not
    installed, then check if it can be installed, and then install or fail.
    After the tool instance returned, the run/Async of the tool will call
    execute/Async of node. So that the command passes to current node.

    The must be implemented methods are marked with @abstractmethod, includes,

    command: it's the command name, like echo, ntttcp. it uses in run/Async to
    run it, and isInstalledInternal to check if it's installed.

    The should be implemented methods throws NotImplementedError, but not marked
    as abstract method, includes,

    can_install: specify if a tool can be installed or not. If a tool is not
    builtin, it must implement this method.

    _install: If a tool is not builtin, it must implement this method. This
    method needs to install a tool, and make sure it can be detected by
    isInstalledInternal.

    The may be implemented methods is empty, includes,

    initialize: It's called when a tool is created, and before to call any other
    methods. It can be used to initialize variables or time-costing operations.

    dependencies: All depended tools, they will be checked and installed before
    current tool installed. For example, ntttcp uses git to clone code and
    build. So it depends on Git tool.

    See details on method descriptions.
    """

    def __init__(self, node: Node, *args: Any, **kwargs: Any) -> None:
        """
        It's not recommended to replace this __init__ method. Anything need to be
        initialized, should be in initialize() method.
        """
        super().__init__()
        self.node: Node = node
        # triple states, None means not checked.
        self._exists: Optional[bool] = None
        self._log = get_logger("tool", self.name, self.node.log)
        # specify the tool is in sudo or not. It may be set to True in
        # _check_exists
        self._use_sudo: bool = False
        # cache the processes with same command line, so that it reduce time to
        # rerun same commands.
        self.__cached_results: Dict[str, Process] = {}

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

    @property
    def command(self) -> str:
        """
        Return command string, which can be run in console. For example, echo.
        The command can be different under different conditions. For example,
        package management is 'yum' on CentOS, but 'apt' on Ubuntu.
        """
        raise NotImplementedError("'command' is not implemented")

    @property
    def can_install(self) -> bool:
        """
        Indicates if the tool supports installation or not. If it can return true,
        installInternal must be implemented.
        """
        raise NotImplementedError("'can_install' is not implemented")

    @property
    def package_name(self) -> str:
        """
        return package name,
        it may be different with command or different platform.
        """
        return self.command

    @property
    def dependencies(self) -> List[Type[Tool]]:
        """
        Declare all dependencies here, it can be other tools, but prevent to be a
        circle dependency. The dependent tools are checked and installed firstly.
        """
        return []

    @property
    def name(self) -> str:
        """
        Unique name to a tool and used as path of tool. Don't change it, or there may
        be unpredictable behavior.
        """
        return self.__class__.__name__.lower()

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

    @classmethod
    def create(cls, node: Node, *args: Any, **kwargs: Any) -> Tool:
        """
        if there is a windows version tool, return the windows instance.
        override this method if richer creation factory is needed.
        """
        tool_cls = cls
        if not node.is_posix:
            windows_tool = cls._windows_tool()
            if windows_tool:
                tool_cls = windows_tool
        elif "FreeBSD" in node.os.name:
            freebsd_tool = cls._freebsd_tool()
            if freebsd_tool:
                tool_cls = freebsd_tool
        elif "VMWareESXi" in node.os.name:
            vmware_esxi_tool = cls._vmware_esxi_tool()
            if vmware_esxi_tool:
                tool_cls = vmware_esxi_tool
        return tool_cls(node, *args, **kwargs)

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        """
        return a windows version tool class, if it's needed
        """
        return None

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        """
        return a freebsd version tool class, if it's needed
        """
        return None

    @classmethod
    def _vmware_esxi_tool(cls) -> Optional[Type[Tool]]:
        """
        return a vmware esxi version tool class, if it's needed
        """
        return None

    def command_exists(self, command: str) -> Tuple[bool, bool]:
        exists = False
        use_sudo = False
        if self.node.is_posix:
            if "VMWareESXi" in self.node.os.name:
                where_command = "which"
            else:
                where_command = "command -v"
        else:
            where_command = "where"
        where_command = f"{where_command} {command}"
        result = self.node.execute(where_command, shell=True, no_info_log=True)
        if result.exit_code == 0:
            exists = True
            use_sudo = False
        elif self.node.is_posix:
            result = self.node.execute(
                where_command,
                shell=True,
                no_info_log=True,
                sudo=True,
            )
            if result.exit_code == 0:
                self._log.debug(
                    "executable exists in root paths, "
                    "sudo always brings in following commands."
                )
                exists = True
                use_sudo = True
        else:
            # for Windows, where is not enough to check if a full path exists,
            # use dir to try again.
            test_command = f"powershell test-path '{command}'"
            result = self.node.execute(test_command, shell=True, no_info_log=True)
            exists = result.stdout == "True"
        return exists, use_sudo

    def install(self) -> bool:
        """
        Default behavior of install a tool, including dependencies. It doesn't need to
        be overridden.
        """
        # check dependencies
        if self.dependencies:
            self._log.info("installing dependencies")
            list(map(self.node.tools.get, self.dependencies))

        return self._install()

    def run_async(
        self,
        parameters: str = "",
        force_run: bool = False,
        shell: bool = False,
        sudo: bool = False,
        nohup: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        no_debug_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
        update_envs: Optional[Dict[str, str]] = None,
        # node uses for guest nodes.
        node: Optional["Node"] = None,
        encoding: str = "",
    ) -> Process:
        """
        Run a command async and return the Process. The process is used for async, or
        kill directly.
        """
        if parameters:
            command = f"{self.command} {parameters}"
        else:
            command = self.command

        # If the command exists in sbin, use the root permission, even the sudo
        # is not specified.
        sudo = sudo or self._use_sudo
        command_key = f"{command}|{shell}|{sudo}|{cwd}"
        process = self.__cached_results.get(command_key, None)
        if node is None:
            node = self.node
        if force_run or not process:
            process = node.execute_async(
                command,
                shell=shell,
                sudo=sudo,
                nohup=nohup,
                no_error_log=no_error_log,
                no_info_log=no_info_log,
                no_debug_log=no_debug_log,
                cwd=cwd,
                update_envs=update_envs,
                encoding=encoding,
            )
            self.__cached_results[command_key] = process
        else:
            self._log.debug(f"loaded cached result for command: [{command}]")
        return process

    def run(
        self,
        parameters: str = "",
        force_run: bool = False,
        shell: bool = False,
        sudo: bool = False,
        nohup: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        no_debug_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
        update_envs: Optional[Dict[str, str]] = None,
        encoding: str = "",
        timeout: int = 600,
        expected_exit_code: Optional[int] = None,
        expected_exit_code_failure_message: str = "",
    ) -> ExecutableResult:
        """
        Run a process and wait for result.
        """
        process = self.run_async(
            parameters=parameters,
            force_run=force_run,
            shell=shell,
            sudo=sudo,
            nohup=nohup,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            no_debug_log=no_debug_log,
            cwd=cwd,
            update_envs=update_envs,
            encoding=encoding,
        )
        return process.wait_result(
            timeout=timeout,
            expected_exit_code=expected_exit_code,
            expected_exit_code_failure_message=expected_exit_code_failure_message,
        )

    def get_tool_path(self, use_global: bool = False) -> pathlib.PurePath:
        """
        compose a path, if the tool need to be installed
        """
        if use_global:
            # change from lisa_working/20220126/20220126-194017-621 to
            # lisa_working. The self.node.generate_working_path will determinate
            # if it's Windows or Linux.
            working_path = self.node.get_working_path().parent.parent
        else:
            assert self.node.working_path, "working path is not initialized"
            working_path = self.node.working_path
        path = working_path.joinpath(constants.PATH_TOOL, self.name)
        self.node.shell.mkdir(path, exist_ok=True)
        return path

    def _install(self) -> bool:
        """
        Execute installation process like build, install from packages. If other tools
        are depended, specify them in dependencies. Other tools can be used here,
        refer to ntttcp implementation.
        """
        raise NotImplementedError("'install' is not implemented")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        Declare and initialize variables here, or some time costing initialization.
        This method is called before other methods, when initialing on a node.
        """
        ...

    def _check_exists(self) -> bool:
        """
        Default implementation to check if a tool exists. This method is called by
        isInstalled, and cached result. Builtin tools can override it can return True
        directly to save time.
        """
        exists, self._use_sudo = self.command_exists(self.command)
        return exists


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
        force_run: bool = False,
        shell: bool = False,
        sudo: bool = False,
        nohup: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        no_debug_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
        update_envs: Optional[Dict[str, str]] = None,
        node: Optional["Node"] = None,
        encoding: str = "",
    ) -> Process:
        if cwd is not None:
            raise LisaException("don't set cwd for script")

        return super().run_async(
            parameters=parameters,
            force_run=force_run,
            shell=shell,
            sudo=sudo,
            nohup=nohup,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            no_debug_log=no_debug_log,
            cwd=self._cwd,
            update_envs=update_envs,
            node=node,
            encoding=encoding,
        )

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
        # the underlying '_check_exists' doesn't work for script but once it's
        # cached in node, it won't be copied again. So it doesn't need to check
        # exists.
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
            if self.node.is_posix:
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
            if file.is_absolute():
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
        command_identifier = constants.NORMALIZE_PATTERN.sub("-", command_identifier)
        hash_source = "".join(files).encode("utf-8")
        hash_result = sha256(hash_source).hexdigest()[:8]
        self.name = f"custom-{command_identifier}-{hash_result}".lower()

    def build(self, node: Node) -> CustomScript:
        return CustomScript(
            self.name, node, self._local_rootpath, self._files, self._command
        )


class Tools:
    def __init__(self, node: Node) -> None:
        self._node = node
        self._cache: Dict[str, Tool] = {}

    def __getattr__(self, key: str) -> Tool:
        """
        for shortcut access like node.tools.echo.call_method()
        """
        return self.__getitem__(key)

    def __getitem__(self, tool_type: Union[Type[T], CustomScriptBuilder, str]) -> T:
        return self.get(tool_type=tool_type)

    def create(
        self,
        tool_type: Union[Type[T], CustomScriptBuilder, str],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Create a new tool with given arguments. Call it only when a new tool is
        needed. Otherwise, call the get method.
        """
        tool_key = self._get_tool_key(tool_type)
        tool = self._cache.get(tool_key, None)
        if tool:
            del self._cache[tool_key]
        return self.get(tool_type, *args, **kwargs)

    def get(
        self,
        tool_type: Union[Type[T], Type[Tool], CustomScriptBuilder, str],
        *args: Any,
        **kwargs: Any,
    ) -> T:
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
        tool_key = self._get_tool_key(tool_type)
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
                tool = cast_tool_type.create(self._node, *args, **kwargs)

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

    def _get_tool_key(self, tool_type: Union[type, CustomScriptBuilder, str]) -> str:
        if isinstance(tool_type, CustomScriptBuilder):
            tool_key = tool_type.name
        elif isinstance(tool_type, str):
            tool_key = tool_type.lower()
        else:
            tool_key = tool_type.__name__.lower()

        return tool_key
