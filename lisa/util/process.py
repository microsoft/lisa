# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import io
import logging
import pathlib
import re
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import spur
from assertpy.assertpy import AssertionBuilder, assert_that, fail
from retry import retry
from spur.errors import NoSuchCommandError

from lisa.util import (
    LisaException,
    RequireUserPasswordException,
    SshSpawnTimeoutException,
    create_timer,
    filter_ansi_escape,
)
from lisa.util.logger import Logger, LogWriter, add_handler, get_logger
from lisa.util.shell import Shell, SshShell

# [sudo] password for lisatest: \r\nsudo: timed out reading password
# Password: \r\nsudo: timed out reading password
TIMEOUT_READING_PASSWORD_PATTERNS = [
    re.compile(r"\[sudo\] password for.+\r\nsudo: timed out reading password"),
    re.compile(r"Password: .+\r\nsudo: timed out reading password"),
]


@dataclass
class ExecutableResult:
    _stdout: str
    _stderr: str
    exit_code: Optional[int]
    cmd: Union[str, List[str]]
    elapsed: float
    is_timeout: bool = False

    def __str__(self) -> str:
        return self.stdout

    @property
    def stdout(self) -> str:
        return filter_ansi_escape(self._stdout)

    @stdout.setter
    def stdout(self, value: str) -> None:
        self._stdout = value

    @property
    def stderr(self) -> str:
        return filter_ansi_escape(self._stderr)

    @stderr.setter
    def stderr(self, value: str) -> None:
        self._stderr = value

    def assert_exit_code(
        self,
        expected_exit_code: Union[int, List[int]] = 0,
        message: str = "",
        include_output: bool = False,
    ) -> AssertionBuilder:
        message = "\n".join([message, f"Get unexpected exit code on cmd {self.cmd}"])
        if include_output:
            message = "\n".join(
                [message, "stdout:", self.stdout, "stderr:", self.stderr]
            )
        # make the type checker happy by not using the union
        expected_exit_codes: List[int] = []
        if isinstance(expected_exit_code, int):
            expected_exit_codes = [expected_exit_code]
        elif isinstance(expected_exit_code, list):
            expected_exit_codes = expected_exit_code
        else:
            fail(
                f"Unexpected type {str(type(expected_exit_code))} was "
                "passed as parameter expected_exit_code. Must be int or "
                "List[int]"
            )

        return assert_that(expected_exit_codes, message).contains(self.exit_code)

    def save_stdout_to_file(self, saved_path: Path) -> "ExecutableResult":
        with open(saved_path, "w") as f:
            f.write(self.stdout)
        return self


def _create_exports(update_envs: Dict[str, str]) -> str:
    result: str = ""

    for key, value in update_envs.items():
        value = value.replace('"', '\\"')
        result += f'export {key}="{value}";'

    return result


def _retry_spawn(func: Callable[..., Any]) -> Any:
    # wrap to pass in the logger object of the current process.
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        return retry(
            exceptions=SshSpawnTimeoutException,
            tries=3,
            delay=1,
            backoff=3,
            logger=self._log,
        )(func)(self, *args, **kwargs)

    return wrapper


def process_posix_command(
    command: str, sudo: bool, shell: bool, nohup: bool, update_envs: Dict[str, str]
) -> List[str]:
    if shell:
        split_command = []
        if sudo:
            split_command += ["sudo"]
        if nohup:
            split_command += ["nohup"]
        envs = _create_exports(update_envs=update_envs)
        if envs:
            command = f"{envs} {command}"

        split_command += ["sh", "-c", command]
        # expand variables in posix mode
        update_envs.clear()
    else:
        if sudo:
            command = f"sudo {command}"
        if nohup:
            command = f"nohup {command}"
        try:
            split_command = shlex.split(command, posix=True)
        except Exception as e:
            raise LisaException(f"failed on split command: {command}: {e}")

    return split_command


def process_windows_command(
    command: str, sudo: bool, shell: bool, nohup: bool, update_envs: Dict[str, str]
) -> List[str]:
    if shell:
        split_command = ["cmd", "/c", command]
    else:
        try:
            split_command = shlex.split(command, posix=False)
        except Exception as e:
            raise LisaException(f"failed on split command: {command}: {e}")

    return split_command


def process_command(
    is_posix: bool,
    command: str,
    sudo: bool,
    shell: bool,
    nohup: bool,
    update_envs: Dict[str, str],
) -> List[str]:
    # command may be Path object, convert it to str
    command = str(command)

    if is_posix:
        split_command = process_posix_command(
            command=command,
            sudo=sudo,
            shell=shell,
            nohup=nohup,
            update_envs=update_envs,
        )
    else:
        split_command = process_windows_command(
            command=command,
            sudo=sudo,
            shell=shell,
            nohup=nohup,
            update_envs=update_envs,
        )

    return split_command


class Process:
    def __init__(
        self,
        id_: str,
        shell: Shell,
        parent_logger: Optional[Logger] = None,
    ) -> None:
        # the shell can be LocalShell or SshShell
        self._shell = shell
        self._id_ = id_
        self._is_posix = shell.is_posix
        self._running: bool = False
        self._log = get_logger("cmd", id_, parent=parent_logger)
        self._process: Optional[spur.local.LocalProcess] = None
        self._result: Optional[ExecutableResult] = None
        self._sudo: bool = False
        self._nohup: bool = False

        # add a string stream handler to the logger
        self.log_buffer = io.StringIO()
        self.log_buffer_offset = 0

    @_retry_spawn
    def start(
        self,
        command: str,
        shell: bool = False,
        sudo: bool = False,
        nohup: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
        update_envs: Optional[Dict[str, str]] = None,
        no_error_log: bool = False,
        no_info_log: bool = False,
        no_debug_log: bool = False,
        encoding: str = "utf-8",
        command_splitter: Callable[..., List[str]] = process_command,
    ) -> None:
        """
        command include all parameters also.
        """
        stdout_level = logging.INFO
        stderr_level = logging.ERROR

        if no_debug_log:
            stdout_level = logging.NOTSET
        elif no_info_log:
            stdout_level = logging.DEBUG

        if no_error_log:
            stderr_level = stdout_level

        self.stdout_logger = get_logger("stdout", parent=self._log)
        self.stderr_logger = get_logger("stderr", parent=self._log)
        self._stdout_writer = LogWriter(logger=self.stdout_logger, level=stdout_level)
        self._stderr_writer = LogWriter(logger=self.stderr_logger, level=stderr_level)

        self._log_handler = logging.StreamHandler(self.log_buffer)
        msg_only_format = logging.Formatter(fmt="%(message)s", datefmt="")
        add_handler(self._log_handler, self.stdout_logger, msg_only_format)
        add_handler(self._log_handler, self.stderr_logger, msg_only_format)

        self._sudo = sudo
        self._nohup = nohup

        if update_envs is None:
            update_envs = {}

        if update_envs and self._is_posix:
            # envs are supported in bash only. If there are envs, force the bash
            # mode.
            shell = True

        update_envs = update_envs.copy()
        split_command = command_splitter(
            self._is_posix, command, sudo, shell, nohup, update_envs
        )

        cwd_path: Optional[str] = None
        if cwd:
            if self._is_posix:
                cwd_path = str(pathlib.PurePosixPath(cwd))
            else:
                cwd_path = str(pathlib.PureWindowsPath(cwd))

        self._log.debug(
            f"cmd: {split_command}, "
            f"cwd: {cwd_path}, "
            f"shell: {shell}, "
            f"sudo: {sudo}, "
            f"nohup: {nohup}, "
            f"posix: {self._is_posix}, "
            f"remote: {self._shell.is_remote}, "
            f"encoding: {encoding}"
        )

        if self._is_posix and self._shell.is_remote:
            # only enable pty on remote Linux
            use_pty = True
        else:
            use_pty = False

        try:
            self._timer = create_timer()
            self._process = self._shell.spawn(
                command=split_command,
                stdout=self._stdout_writer,
                stderr=self._stderr_writer,
                cwd=cwd_path,
                update_env=update_envs,
                allow_error=True,
                store_pid=True,
                encoding=encoding,
                use_pty=use_pty,
            )
            # save for logging.
            self._cmd = split_command
            self._running = True

            # set keep alive for ssh connection, it avoids the connection being
            # closed without any data transfer.
            if self._shell.is_remote:
                self._process._channel.transport.set_keepalive(30)
        except (FileNotFoundError, NoSuchCommandError) as e:
            # FileNotFoundError: not found command on Windows
            # NoSuchCommandError: not found command on remote Posix
            self._result = ExecutableResult(
                "", e.strerror, 1, split_command, self._timer.elapsed()
            )
            self._log.log(stderr_level, f"not found command: {e}")
        except SshSpawnTimeoutException:
            # close the shell and try again, see if the ssh connection is interrupted.
            self._shell.close()
            raise

        self.check_and_input_password()

    def check_and_input_password(self) -> None:
        if (
            self._sudo
            and isinstance(self._shell, SshShell)
            and self._shell.is_sudo_required_password
        ):
            timer = create_timer()
            while self.is_running():
                time.sleep(0.01)
                if timer.elapsed(False) > 0.5:
                    if not self._shell.connection_info.password:
                        raise RequireUserPasswordException(
                            "Running commands with sudo requires user's password,"
                            " but no password is provided."
                        )
                    self.input(f"{self._shell.connection_info.password}\n", False)
                    self._log.debug("The user's password is input")
                    break

    def input(self, content: str, is_log_input: bool = True) -> None:
        assert self._process, "The process object is None, the process may end."
        if is_log_input:
            self._log.debug(f"input content: {content}")
        else:
            self._log.debug(f"Inputting {len(content)} chars to process.")
        self._process.stdin_write(content)

    def wait_result(
        self,
        timeout: float = 600,
        expected_exit_code: Optional[int] = None,
        expected_exit_code_failure_message: str = "",
    ) -> ExecutableResult:
        timer = create_timer()
        is_timeout = False

        while self.is_running() and timeout >= timer.elapsed(False):
            time.sleep(0.01)

        if timeout < timer.elapsed():
            if self._process is not None:
                self._log.info(f"timeout in {timeout} sec, and killed")
            self.kill()
            is_timeout = True

        if self._result is None:
            assert self._process
            if is_timeout:
                # LogWriter only flushes if "\n" is written, so we need to flush
                # manually.
                self._stdout_writer.flush()
                self._stderr_writer.flush()
                process_result = spur.results.result(
                    return_code=1,
                    allow_error=True,
                    output=self.log_buffer.getvalue(),
                    stderr_output="",
                )
            else:
                process_result = self._process.wait_for_result()
            if not self._is_posix and self._shell.is_remote:
                # special handle remote windows. There are extra control chars
                # and on extra line at the end.

                # remove extra controls in remote Windows
                process_result.output = filter_ansi_escape(process_result.output)
                process_result.stderr_output = filter_ansi_escape(
                    process_result.stderr_output
                )

            self._stdout_writer.close()
            self._stderr_writer.close()
            # cache for future queries, in case it's queried twice.
            self._result = ExecutableResult(
                process_result.output.strip(),
                process_result.stderr_output.strip(),
                process_result.return_code,
                self._cmd,
                self._timer.elapsed(),
                is_timeout,
            )

            self._recycle_resource()

            if not self._is_posix:
                # convert windows error code to int4, so it's more friendly.
                assert self._result.exit_code is not None
                exit_code = self._result.exit_code
                if exit_code > 2**31:
                    self._result.exit_code = exit_code - 2**32

            self._log.debug(
                f"execution time: {self._timer}, exit code: {self._result.exit_code}"
            )

        if expected_exit_code is not None:
            self._result.assert_exit_code(
                expected_exit_code=expected_exit_code,
                message=expected_exit_code_failure_message,
            )

        if self._is_posix and self._sudo:
            self._result.stdout = self._filter_sudo_result(self._result.stdout)

        self._result.stdout = self._filter_profile_error(self._result.stdout)
        self._result.stdout = self._filter_bash_prompt(self._result.stdout)
        self._check_if_need_input_password(self._result.stdout)
        self._result.stdout = self._filter_sudo_required_password_info(
            self._result.stdout
        )

        if not self._is_posix:
            # fix windows ending with " by some unknown reason.
            self._result.stdout = self._remove_ending_quote(self._result.stdout)
            self._result.stderr = self._remove_ending_quote(self._result.stderr)

        return self._result

    def kill(self) -> None:
        if (
            isinstance(self._shell, SshShell)
            and self._shell._inner_shell
            and self._shell._inner_shell._spur._shell_type
            == spur.ssh.ShellTypes.minimal
        ):
            self._log.debug("skip killing process on minimal shell")
            return
        if self._process:
            self._log.debug(f"Killing process : {self._id_}, pid: {self._process.pid}")
            try:
                if self._is_posix:
                    if self._shell.is_remote:
                        # Support remote Posix so far
                        self._process.send_signal(9)
                    else:
                        # local process should use the compiled value
                        # the value is different between windows and posix
                        self._process.send_signal(signal.SIGTERM)
                else:
                    # windows
                    task_kill = "taskkill"
                    kill_process = Process(
                        task_kill, self._shell, parent_logger=self._log
                    )
                    kill_process.start(
                        f"{task_kill} /F /T /PID " + str(self._process.pid),
                        no_info_log=True,
                    )
                    kill_process.wait_result(1)
            except Exception as e:
                self._log.debug(f"failed on killing process: {e}")

    def is_running(self) -> bool:
        if self._running and self._process:
            self._running = self._process.is_running()
        return self._running

    def wait_output(
        self,
        keyword: str,
        timeout: int = 300,
        error_on_missing: bool = True,
        interval: float = 1,
        delta_only: bool = False,
    ) -> bool:
        # check if stdout buffers contain the string "keyword" to determine if
        # it is running
        start_time = time.time()
        while time.time() - start_time < timeout:
            # LogWriter only flushes if "\n" is written, so we need to flush
            # manually.
            self._stdout_writer.flush()
            self._stderr_writer.flush()

            # check if buffer contains the keyword
            find_pos = self.log_buffer_offset if delta_only else 0
            if self.log_buffer.getvalue().find(keyword, find_pos) >= 0:
                self.log_buffer_offset = len(self.log_buffer.getvalue())
                return True

            time.sleep(interval)

        self.log_buffer_offset = len(self.log_buffer.getvalue())

        if error_on_missing:
            raise LisaException(
                f"{keyword} not found in stdout after {timeout} seconds"
            )
        else:
            self._log.debug(
                f"not found '{keyword}' in {timeout} seconds, but ignore it."
            )

        return False

    def _recycle_resource(self) -> None:
        # TODO: The spur library is not very good and leaves open
        # resources (probably due to it starting the process with
        # `bufsize=0`). We need to replace it, but for now, we
        # manually close the leaks.
        if isinstance(self._process, spur.local.LocalProcess):
            popen: subprocess.Popen[str] = self._process._subprocess
            if popen.stdin:
                popen.stdin.close()
            if popen.stdout:
                popen.stdout.close()
            if popen.stderr:
                popen.stderr.close()
        elif isinstance(self._process, spur.ssh.SshProcess):
            if self._process._stdin:
                self._process._stdin.close()
            if self._process._stdout:
                self._process._stdout.close()
            if self._process._stderr:
                self._process._stderr.close()
        self._process = None

    def _filter_sudo_result(self, raw_input: str) -> str:
        # this warning message may break commands, so remove it from the first line
        # of standard output.
        if raw_input.startswith("sudo: unable to resolve host"):
            lines = [
                line for line in raw_input.splitlines(keepends=True) if line.strip()
            ]
            raw_input = "".join(lines[1:])
            self._log.debug(f'found error message in sudo: "{lines[0]}"')
        return raw_input

    def _filter_profile_error(self, raw_input: str) -> str:
        # If there is CommandInitializationError when calling spawn, the stdout has that
        # error line before the output of every command. E.g. the stdout of command
        # "uname -vrmo" is like: '/etc/profile.d/clover.sh: line 10: /opt/clover/bin/
        # prepare-hostname.sh: Permission denied\r\n0\r\n3.10.0-1160.88.1.el7.x86_64
        # #1 SMP Tue Mar 7 15:41:52 UTC 2023 x86_64 GNU/Linux'
        # Other example:
        # '/etc/profile.d/vglrun.sh: line 3: lspci: command not found\r\nDescription:\t
        # CentOS Linux release 7.9.2009 (Core)'
        # So remove the error line
        if (
            isinstance(self._shell, SshShell)
            and self._shell.spawn_initialization_error_string
            and self._shell._inner_shell
            and self._shell._inner_shell._spur._shell_type
            == spur.ssh.ShellTypes.minimal
        ):
            raw_input = raw_input.replace(
                f"{self._shell.spawn_initialization_error_string}\n", ""
            )
            raw_input = raw_input.replace(
                f"{self._shell.spawn_initialization_error_string}\r\n", ""
            )
            self._log.debug(
                "filter the profile error string: "
                f"{self._shell.spawn_initialization_error_string}"
            )
        return raw_input

    def _filter_bash_prompt(self, raw_input: str) -> str:
        # some images have bash prompt in stdout, remove it.
        # E.g. yaseensmarket1645449809728 wordpress-red-hat
        # ----------------------------------------------------------------------
        # Use the this command 'sudo bash ~/getcert.sh' to install a certificate
        # ----------------------------------------------------------------------
        if isinstance(self._shell, SshShell) and self._shell.bash_prompt:
            raw_input = raw_input.replace(self._shell.bash_prompt, "")
        return raw_input

    def _check_if_need_input_password(self, raw_input: str) -> None:
        # Check if the stdout contains "[sudo] password for .*: " and
        # "sudo: timed out reading password" strings. If so, raise exception
        for pattern in TIMEOUT_READING_PASSWORD_PATTERNS:
            if re.search(pattern, raw_input):
                raise RequireUserPasswordException(
                    "Timed out reading password. "
                    "Running commands with sudo requires user's password"
                )

    def _filter_sudo_required_password_info(self, raw_input: str) -> str:
        # If system needs input of password when running commands with sudo, the output
        # might have below lines:
        # We trust you have received the usual lecture from the local System
        # Administrator. It usually boils down to these three things:
        #
        #     #1) Respect the privacy of others.
        #     #2) Think before you type.
        #     #3) With great power comes great responsibility.
        #
        # [sudo] password for l****t:
        # After inputting the right password, the output might have the following line
        # when running commands with sudo next time.
        # [sudo] password for l****t:
        # Remove these lines
        if (
            self._sudo
            and isinstance(self._shell, SshShell)
            and self._shell.is_sudo_required_password
        ):
            for prompt in self._shell.password_prompts:
                raw_input = raw_input.replace(prompt, "")
        return raw_input

    def _remove_ending_quote(self, raw_input: str) -> str:
        # remove ending " by some unknown reason.
        if raw_input.startswith('"'):
            # if it starts with quote, don't remove it.
            return raw_input

        if raw_input.endswith('"'):
            self._log.debug(
                "Removed ending quote from output. "
                "If it's unexpected, avoid to have ending quote in Windows output."
            )
            raw_input = raw_input[:-1]
        return raw_input
