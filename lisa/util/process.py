import os
import subprocess
import logging
from threading import Thread
import psutil

from lisa.common import log


class LogPipe(Thread):
    def __init__(self, level):
        """Setup the object with a logger and a loglevel
        and start the thread
        """
        Thread.__init__(self)
        self.daemon = False
        self.level = level
        self.fdRead, self.fdWrite = os.pipe()
        self.pipeReader = os.fdopen(self.fdRead)
        self.start()

    def fileno(self):
        """Return the write file descriptor of the pipe
        """
        return self.fdWrite

    def run(self):
        """Run the thread, logging everything.
        """
        for line in iter(self.pipeReader.readline, ""):
            log.log(self.level, line.strip("\n"))

        self.pipeReader.close()

    def close(self):
        """Close the write end of the pipe.
        """
        os.close(self.fdWrite)


class Process:
    def __init__(self):
        self.process = None
        self.exitCode = None
        self.running = None
        self.log_pipe = None

    def start(self, command: str, cwd: str = None, new_envs: dict = None):
        """
            command include all parameters also.
        """
        environ = os.environ.copy()
        if new_envs is not None:
            for key, value in new_envs:
                environ[key] = value
        self.stdout_pipe = LogPipe(logging.INFO)
        self.stderr_pipe = LogPipe(logging.ERROR)
        self.process = subprocess.Popen(
            command,
            shell=True,
            stdout=self.stdout_pipe,
            stderr=self.stderr_pipe,
            cwd=cwd,
            env=dict(environ),
        )
        self.running = True
        log.debug("process %s started", self.process.pid)

    def stop(self):
        if self.process is not None:
            for child in psutil.Process(self.process.pid).children(True):
                child.terminate()
            self.process.terminate()
            log.debug("process %s stopped", self.process.pid)

    def cleanup(self):
        if self.self.stdout_pipe is not None:
            self.self.stdout_pipe.close()
        if self.self.stderr_pipe is not None:
            self.self.stderr_pipe.close()

    def isRunning(self):
        self.exitCode = self.getExitCode()
        if self.exitCode is not None:
            if self.running:
                log.debug(
                    "process %s exited: %s", self.process.pid, self.exitCode
                )
            self.running = False
        return self.running

    def getExitCode(self):
        if self.process is not None:
            self.exitCode = self.process.poll()
        return self.exitCode
