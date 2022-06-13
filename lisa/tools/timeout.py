# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath

from lisa.executable import ExecutableResult, Process, Tool
from lisa.operating_system import Posix

""" from `man timeout`
Usage: timeout [OPTION] DURATION COMMAND [ARG]...
  or:  timeout [OPTION]
Start COMMAND, and kill it if still running after DURATION.

Mandatory arguments to long options are mandatory for short options too.
      --preserve-status
                 exit with the same status as COMMAND, even when the
                   command times out
      --foreground
                 when not running timeout directly from a shell prompt,
                   allow COMMAND to read from the TTY and get TTY signals;
                   in this mode, children of COMMAND will not be timed out
  -k, --kill-after=DURATION
                 also send a KILL signal if COMMAND is still running
                   this long after the initial signal was sent
  -s, --signal=SIGNAL
                 specify the signal to be sent on timeout;
                   SIGNAL may be a name like 'HUP' or a number;
                   see 'kill -l' for a list of signals
"""


class Timeout(Tool):
    @property
    def command(self) -> str:
        return "timeout"

    def _install(self) -> bool:
        assert isinstance(
            self.node.os, Posix
        ), f"timeout is only supported on *nix systems {self.node.os.name}"
        self.node.os.install_packages("coreutils")
        return self._check_exists()

    def timeout_async(
        self,
        command: str,
        preserve_child_exit_status: bool,
        timeout: int,
        cwd: PurePath,
        sudo: bool = False,
        send_signal: str = "KILL",
        kill_timeout: int = 0,
    ) -> Process:

        args = " "

        # preserve the exit status of the child command
        # will return the child exit status when `timeout`
        # times out. Otherwise timeout will return an error if the command
        # didn't finish before the timeout.
        if preserve_child_exit_status:
            args += "--preserve-status "

        # kill timeout provides a second timer that always sends 'KILL'
        # to be used as a backup in case the first signal doesn't exit nicely.
        if kill_timeout:
            args += f"-k {kill_timeout} "

        args += f"-s {send_signal} {timeout} {command}"

        return self.run_async(
            args,
            force_run=True,
            shell=True,
            sudo=sudo,
            cwd=cwd,
        )

    def timeout(
        self,
        command: str,
        preserve_child_exit_status: bool,
        timeout: int,
        cwd: PurePath,
        sudo: bool = False,
        send_signal: str = "KILL",
        kill_timeout: int = 0,
        expected_exit_code: int | None = None,
        expected_exit_code_failure_message: str = "",
    ) -> ExecutableResult:
        process = self.timeout_async(
            command,
            preserve_child_exit_status,
            timeout,
            cwd=cwd,
            sudo=sudo,
            send_signal=send_signal,
            kill_timeout=kill_timeout,
        )
        return process.wait_result(
            expected_exit_code=expected_exit_code,
            expected_exit_code_failure_message=expected_exit_code_failure_message,
        )
