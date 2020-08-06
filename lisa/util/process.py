import logging
import os
import shlex
import subprocess
from threading import Thread
from typing import Any, Dict, List, Optional, cast

import psutil

from lisa.common.logger import log


class LogPipe(Thread):
    def __init__(self, level: int):
        """Setup the object with a logger and a loglevel
        and start the thread
        """
        Thread.__init__(self)
        self.daemon = False
        self.level = level
        self.fdRead, self.fdWrite = os.pipe()
        self.pipeReader = os.fdopen(self.fdRead)
        self.start()

    def fileno(self) -> int:
        """Return the write file descriptor of the pipe
        """
        return self.fdWrite

    def run(self) -> None:
        """Run the thread, logging everything.
        """
        for line in iter(self.pipeReader.readline, ""):
            log.log(self.level, line.strip("\n"))

        self.pipeReader.close()

    def close(self) -> None:
        """Close the write end of the pipe.
        """
        os.close(self.fdWrite)


class Process:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen[Any]] = None
        self.exitCode: Optional[int] = None
        self.running: bool = False
        self.log_pipe: Optional[LogPipe] = None

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
        self.running = True
        if self.process is not None:
            log.debug("process %s started", self.process.pid)

    def stop(self) -> None:
        if self.process is not None:
            children = cast(
                List[psutil.Process], psutil.Process(self.process.pid).children(True)
            )
            for child in children:
                child.terminate()
            self.process.terminate()
            log.debug("process %s stopped", self.process.pid)

    def cleanup(self) -> None:
        if self.stdout_pipe is not None:
            self.stdout_pipe.close()
        if self.stderr_pipe is not None:
            self.stderr_pipe.close()

    def isRunning(self) -> bool:
        self.exitCode = self.getExitCode()
        if self.exitCode is not None and self.process is not None:
            if self.running is True:
                log.debug("process %s exited: %s", self.process.pid, self.exitCode)
            self.running = False
        return self.running

    def getExitCode(self) -> Optional[int]:
        if self.process is not None:
            self.exitCode = self.process.poll()
        return self.exitCode
