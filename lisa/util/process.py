import logging
import pathlib
import shlex
import time
from dataclasses import dataclass
from logging import Logger
from typing import TYPE_CHECKING, Dict, Optional, Type

from spur.errors import NoSuchCommandError  # type: ignore

from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer
from lisa.util.shell import Shell

if TYPE_CHECKING:
    BaseExceptionType = Type[BaseException]
else:
    BaseExceptionType = bool


@dataclass
class ExecutableResult:
    stdout: str
    stderr: str
    exit_code: Optional[int]
    elapsed: float

    def __str__(self) -> str:
        return self.stdout


class LogWriter:
    def __init__(self, level: int, log: Logger) -> None:
        self._level = level
        self._log = log
        self._buffer: str = ""

    def write(self, message: str) -> None:
        if message == "\n":
            self._log.log(self._level, self._buffer)
            self._buffer = ""
        else:
            self._buffer = "".join([self._buffer, message])

    def close(self) -> None:
        if len(self._buffer) > 0:
            self._log.log(self._level, self._buffer)


class Process:
    def __init__(
        self,
        id_: str,
        shell: Shell,
        parent_logger: Optional[Logger] = None,
        is_linux: bool = True,
    ) -> None:
        # the shell can be LocalShell or SshShell
        self._shell = shell
        self._id = id_
        self._is_linux = is_linux
        self._running: bool = False
        self._log = get_logger("cmd", id_, parent=parent_logger)

    def start(
        self,
        command: str,
        shell: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
        new_envs: Optional[Dict[str, str]] = None,
        no_error_log: bool = False,
        no_info_log: bool = False,
    ) -> None:
        """
            command include all parameters also.
        """
        stdout_level = logging.INFO
        stderr_level = logging.ERROR
        if no_info_log:
            stdout_level = logging.DEBUG
        if no_error_log:
            stderr_level = stdout_level

        self.stdout_writer = LogWriter(
            stdout_level, get_logger("stdout", parent=self._log)
        )
        self.stderr_writer = LogWriter(
            stderr_level, get_logger("stderr", parent=self._log)
        )

        # command may be Path object, convert it to str
        command = f"{command}"
        if shell:
            if self._is_linux:
                split_command = ["bash", "-c"]
            else:
                split_command = ["cmd", "/c"]
            split_command.append(command)
        else:
            split_command = shlex.split(command, posix=self._is_linux)

        cwd_path: Optional[str] = None
        if cwd:
            if self._is_linux:
                cwd_path = str(pathlib.PurePosixPath(cwd))
            else:
                cwd_path = str(pathlib.PureWindowsPath(cwd))

        self._log.debug(
            f"Linux({1 if self._is_linux else 0})"
            f"Remote({1 if self._shell.is_remote else 0}): "
            f"cmd: {split_command}, "
            f"cwd: {cwd_path}"
        )

        try:
            self._timer = create_timer()
            self._process = self._shell.spawn(
                command=split_command,
                stdout=self.stdout_writer,
                stderr=self.stderr_writer,
                cwd=cwd_path,
                update_env=new_envs,
                allow_error=True,
                store_pid=True,
                encoding="utf-8",
            )
            self._running = True
        except (FileNotFoundError, NoSuchCommandError) as identifier:
            # FileNotFoundError: not found command on Windows
            # NoSuchCommandError: not found command on remote Linux
            self._process = ExecutableResult(
                "", identifier.strerror, 1, self._timer.elapsed()
            )
            self._log.debug(f"not found command: {identifier}")

    def wait_result(self, timeout: float = 600) -> ExecutableResult:
        timer = create_timer()

        while self.is_running() and timeout >= timer.elapsed(False):
            time.sleep(0.01)

        if timeout < timer.elapsed():
            if self._process is not None:
                self._log.warn(f"timeout in {timeout} sec, and killed")
            self.kill()

        if not isinstance(self._process, ExecutableResult):
            assert self._process
            proces_result = self._process.wait_for_result()
            self.stdout_writer.close()
            self.stderr_writer.close()
            result: ExecutableResult = ExecutableResult(
                proces_result.output.strip(),
                proces_result.stderr_output.strip(),
                proces_result.return_code,
                self._timer.elapsed(),
            )
        else:
            result = self._process

        self._log.debug(f"executed with {self._timer}")
        return result

    def kill(self) -> None:
        if self._process and not isinstance(self._process, ExecutableResult):
            self._process.send_signal(9)

    def is_running(self) -> bool:
        if self._running:
            self._running = self._process.is_running()
        return self._running
