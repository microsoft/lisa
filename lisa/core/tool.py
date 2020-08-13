from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional, Type

from lisa.util.executableResult import ExecutableResult
from lisa.util.process import Process

if TYPE_CHECKING:
    from lisa.core.node import Node


class Tool(ABC):
    """
    The base class, which wraps an executable, package, or scripts on a node.
    A tool can be installed, and execute on a node. When a tool is needed, call
    Node.getTool() to get one object. The getTool checks if it's installed. If it's
    not installed, then check if it can be installed, and then install or fail.
    After the tool instance returned, the run/Async of the tool will call
    execute/Async of node. So that the command passes to current node.

    The must be implemented methods are marked with @abstractmethod, includes
    command: it's the command name, like echo, ntttcp. it uses in run/Async to run it,
             and isInstalledInternal to check if it's installed.

    The should be implemented methods throws NotImplementedError, but not marked as
    abstract method, includes,
    canInstall: specify if a tool can be installed or not. If a tool is not builtin, it
                must implement this method.
    installInternal: If a tool is not builtin, it must implement this method. This
                     method needs to install a tool, and make sure it can be detected
                     by isInstalledInternal.

    The may be implemented methods is empty, includes
    initialize: It's called when a tool is created, and before to call any other
                methods. It can be used to initialize variables or time-costing
                operations.
    dependencies: All dependented tools, they will be checked and installed before
                  current tool installed. For example, ntttcp uses git to clone code
                  and build. So it depends on Git tool.

    See details on method descriptions.
    """

    def __init__(self, node: Node) -> None:
        """
        It's not recommended to replace this __init__ method. Anything need to be
        initialized, should be in initialize() method.
        """
        self.node: Node = node
        # triple states, None means not checked.
        self._is_installed: Optional[bool] = None

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

    def _install_internal(self) -> bool:
        """
        Execute installation process like build, install from packages. If other tools
        are dependented, specify them in dependencies. Other tools can be used here,
        refer to ntttcp implementation.
        """
        raise NotImplementedError()

    def initialize(self) -> None:
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
        return self.__class__.__name__

    @property
    def _is_installed_internal(self) -> bool:
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
        self._is_installed = result.exit_code == 0
        return self._is_installed

    @property
    def is_installed(self) -> bool:
        """
        Return if a tool installed. In most cases, overriding inInstalledInternal is
        enough. But if want to disable cached result and check tool every time,
        override this method. Notice, remote operations take times, that why caching is
        necessary.
        """
        # the check may need extra cost, so cache it's result.
        if self._is_installed is None:
            self._is_installed = self._is_installed_internal
        return self._is_installed

    def install(self) -> bool:
        """
        Default behavior of install a tool, including dependencies. It doesn't need to
        be overrided.
        """
        # check dependencies
        for dependency in self.dependencies:
            self.node.get_tool(dependency)
        result = self._install_internal()
        return result

    def runasync(
        self,
        parameters: str = "",
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
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
        process = self.node.executeasync(
            command, shell, no_error_log=no_error_log, cwd=cwd, no_info_log=no_info_log,
        )
        return process

    def run(
        self,
        parameters: str = "",
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        """
        Run a process and wait for result.
        """
        process = self.runasync(
            parameters=parameters,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result()
