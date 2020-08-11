import logging
import pathlib
import shlex
import time
from timeit import default_timer as timer
from typing import TYPE_CHECKING, Dict, Optional, Type

import spur  # type: ignore

from lisa.util.executableResult import ExecutableResult
from lisa.util.logger import log
from lisa.util.shell import Shell

if TYPE_CHECKING:
    BaseExceptionType = Type[BaseException]
else:
    BaseExceptionType = bool


class LogWriter:
    def __init__(self, level: int, cmd_prefix: str = "") -> None:
        self.level = level
        self.cmd_prefix = cmd_prefix
        self.buffer: str = ""

    def write(self, message: str) -> None:
        if message == "\n":
            log.log(self.level, f"{self. cmd_prefix}{self.buffer}")
            self.buffer = ""
        else:
            self.buffer = "".join([self.buffer, message])

    def close(self) -> None:
        if len(self.buffer) > 0:
            log.log(self.level, f"{self.cmd_prefix}{self.buffer}")


class Process:
    def __init__(self, cmd_prefix: str, shell: Shell, isLinux: bool = True) -> None:
        # the shell can be LocalShell or SshShell
        self.shell = shell
        self.cmd_prefix = cmd_prefix
        self.isLinux = isLinux
        self._running: bool = False

    def start(
        self,
        command: str,
        useBash: bool = False,
        cwd: Optional[pathlib.Path] = None,
        new_envs: Optional[Dict[str, str]] = None,
        noErrorLog: bool = False,
        noInfoLog: bool = False,
    ) -> None:
        """
            command include all parameters also.
        """
        stdoutLogLevel = logging.INFO
        stderrLogLevel = logging.ERROR
        if noInfoLog:
            stdoutLogLevel = logging.DEBUG
        if noErrorLog:
            stderrLogLevel = stdoutLogLevel

        self.stdout_writer = LogWriter(stdoutLogLevel, f"{self.cmd_prefix}stdout: ")
        self.stderr_writer = LogWriter(stderrLogLevel, f"{self.cmd_prefix}stderr: ")

        if useBash:
            if self.isLinux:
                split_command = ["bash", "-c"]
            else:
                split_command = ["cmd", "/c"]
            split_command.append(command)
        else:
            split_command = shlex.split(command)
            log.debug(f"split command: {split_command}")

        try:
            real_shell = self.shell.innerShell
            assert real_shell
            self._start_timer = timer()
            self.process = real_shell.spawn(
                command=split_command,
                stdout=self.stdout_writer,
                stderr=self.stderr_writer,
                cwd=cwd,
                update_env=new_envs,
                allow_error=True,
                store_pid=True,
                encoding="utf-8",
            )
            self._running = True
            log.debug(f"{self.cmd_prefix}started")
        except (FileNotFoundError, spur.errors.NoSuchCommandError) as identifier:
            # FileNotFoundError: not found command on Windows
            # NoSuchCommandError: not found command on remote Linux
            self._end_timer = timer()
            self.process = ExecutableResult(
                "", identifier.strerror, 1, self._end_timer - self._start_timer
            )
            log.debug(f"{self.cmd_prefix} not found command")

    def waitResult(self, timeout: float = 600) -> ExecutableResult:
        budget_time = timeout

        while self.isRunning() and budget_time >= 0:
            start = timer()
            time.sleep(0.01)
            end = timer()
            budget_time = budget_time - (end - start)

        if budget_time < 0:
            if self.process is not None:
                log.warn(f"{self.cmd_prefix}timeout in {timeout} sec, and killed")
            self.kill()

        if not isinstance(self.process, ExecutableResult):
            assert self.process
            proces_result = self.process.wait_for_result()
            self._end_timer = timer()
            self.stdout_writer.close()
            self.stderr_writer.close()
            result = ExecutableResult(
                proces_result.output.strip(),
                proces_result.stderr_output.strip(),
                proces_result.return_code,
                self._end_timer - self._start_timer,
            )
        else:
            result = self.process

        log.debug(f"{self.cmd_prefix}executed with {result.elapsed:.3f} sec")
        return result

    def kill(self) -> None:
        if self.process and not isinstance(self.process, ExecutableResult):
            self.process.send_signal(9)

    def isRunning(self) -> bool:
        if self._running:
            self._running = self.process.is_running()
        return self._running
