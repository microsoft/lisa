import logging
import os
import shlex
import subprocess
import time
from threading import Thread
from timeit import default_timer as timer
from types import TracebackType
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, cast

import psutil

from lisa.util.excutableResult import ExecutableResult
from lisa.util.logger import log

if TYPE_CHECKING:
    BaseExceptionType = Type[BaseException]
else:
    BaseExceptionType = bool


class LogPipe(Thread):
    def __init__(self, level: int):
        """Setup the object with a logger and a loglevel
        and start the thread
        """
        Thread.__init__(self)
        self.output: str = ""
        self.daemon = False
        self.level = level
        self.fdRead, self.fdWrite = os.pipe()
        self.pipeReader = os.fdopen(self.fdRead)
        self.isReadCompleted = False
        self.isClosed = False
        self.start()

    def fileno(self) -> int:
        """Return the write file descriptor of the pipe
        """
        return self.fdWrite

    def run(self) -> None:
        """Run the thread, logging everything.
        """
        output = self.pipeReader.read()
        self.output = "".join([self.output, output])
        for line in output.splitlines(False):
            log.log(self.level, line)

        self.pipeReader.close()
        self.isReadCompleted = True

    def close(self) -> None:
        """Close the write end of the pipe.
        """
        if not self.isClosed:
            os.close(self.fdWrite)
            self.isClosed = True


class Process:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen[Any]] = None
        self.exitCode: Optional[int] = None
        self.log_pipe: Optional[LogPipe] = None

        self._running: bool = False

    def __enter__(self) -> None:
        pass

    def __exit__(
        self,
        exc_type: Optional[BaseExceptionType],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.cleanup()

    def start(
        self,
        command: str,
        cwd: Optional[str] = None,
        new_envs: Optional[Dict[str, str]] = None,
    ) -> None:
        """
            command include all parameters also.
        """
        dictEnv = dict(os.environ.copy())
        if new_envs is not None:
            for key, value in new_envs.items():
                dictEnv[key] = value
        self.stdout_pipe = LogPipe(logging.INFO)
        self.stderr_pipe = LogPipe(logging.ERROR)
        args = shlex.split(command)
        self.process = subprocess.Popen(
            args,
            shell=True,
            stdout=cast(int, self.stdout_pipe),
            stderr=cast(int, self.stderr_pipe),
            cwd=cwd,
            env=cast(Optional[Dict[str, str]], dictEnv),
        )
        self._running = True
        if self.process is not None:
            log.debug(f"process {self.process.pid} started")

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
                log.warn(f"process {self.process.pid} timeout in {timeout} sec")
            self.stop()

        # cleanup to get pipe complete
        self.cleanup()

        # wait all content flushed
        while (
            not self.stdout_pipe.isReadCompleted or not self.stderr_pipe.isReadCompleted
        ):
            time.sleep(0.01)
        return ExecutableResult(
            self.stdout_pipe.output, self.stderr_pipe.output, self.exitCode
        )

    def stop(self) -> None:
        if self.process is not None:
            children = cast(
                List[psutil.Process], psutil.Process(self.process.pid).children(True)
            )
            for child in children:
                child.terminate()
            self.process.terminate()
            log.debug(f"process {self.process.pid} stopped")

    def cleanup(self) -> None:
        if self.stdout_pipe is not None:
            self.stdout_pipe.close()
        if self.stderr_pipe is not None:
            self.stderr_pipe.close()

    def isRunning(self) -> bool:
        self.exitCode = self.getExitCode()
        if self.exitCode is not None and self.process is not None:
            if self._running:
                log.debug(f"process {self.process.pid} exited: {self.exitCode}")
            self._running = False
        return self._running

    def getExitCode(self) -> Optional[int]:
        if self.process is not None:
            self.exitCode = self.process.poll()
        return self.exitCode
