import logging
import shlex
import time
from timeit import default_timer as timer
from typing import TYPE_CHECKING, Dict, Optional, Type, Union

import spur
from spurplus import SshShell  # type: ignore

from lisa.util.executableResult import ExecutableResult
from lisa.util.logger import log

if TYPE_CHECKING:
    BaseExceptionType = Type[BaseException]
else:
    BaseExceptionType = bool


class LogWriter:
    def __init__(self, level: int, cmd_prefix: str = ""):
        self.level = level
        self.cmd_prefix = cmd_prefix
        self.buffer: str = ""

    def write(self, message: str):
        if message == "\n":
            log.log(self.level, f"{self. cmd_prefix}{self.buffer}")
            self.buffer = ""
        else:
            self.buffer = "".join([self.buffer, message])

    def close(self):
        if len(self.buffer) > 0:
            log.log(self.level, f"{self.cmd_prefix}{self.buffer}")


class Process:
    def __init__(
        self, cmd_prefix: str, shell: Union[SshShell, spur.LocalShell]
    ) -> None:
        # the shell can be LocalShell or SshShell
        self.shell = shell
        self.cmd_prefix = cmd_prefix
        self._running: bool = False

    def start(
        self,
        command: str,
        cwd: Optional[str] = None,
        new_envs: Optional[Dict[str, str]] = None,
        noErrorLog: bool = False,
    ) -> None:
        """
            command include all parameters also.
        """
        self.stdout_writer = LogWriter(logging.INFO, f"{self.cmd_prefix}stdout: ")
        if noErrorLog:
            logLevel = logging.INFO
        else:
            logLevel = logging.ERROR
        self.stderr_writer = LogWriter(logLevel, f"{self.cmd_prefix}stderr: ")

        split_command = shlex.split(command)
        log.debug(f"split command: {split_command}")
        try:
            self.process = self.shell.spawn(
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
            self.process = ExecutableResult("", identifier.strerror, 1,)
            log.debug(f"{self.cmd_prefix} not found command")

    def waitResult(self, timeout: float = 600) -> ExecutableResult:
        budget_time = timeout
        # wait for all content read
        while self.isRunning() and budget_time >= 0:
            start = timer()
            time.sleep(0.01)
            end = timer()
            budget_time = budget_time - (end - start)

        if budget_time < 0:
            if self.process is not None:
                log.warn(f"{self.cmd_prefix}timeout in {timeout} sec, and killed")
            self.stop()

        if not isinstance(self.process, ExecutableResult):
            assert self.process
            proces_result = self.process.wait_for_result()
            self.stdout_writer.close()
            self.stderr_writer.close()
            result = ExecutableResult(
                proces_result.output.strip(),
                proces_result.stderr_output.strip(),
                proces_result.return_code,
            )
        else:
            result = self.process

        return result

    def stop(self) -> None:
        if self.process and not isinstance(self.process, ExecutableResult):
            self.process.send_signal(9)

    def isRunning(self) -> bool:
        if self._running:
            self._running = self.process.is_running()
        return self._running
