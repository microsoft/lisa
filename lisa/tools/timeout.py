from lisa.executable import ExecutableResult, Process, Tool
from lisa.util.constants import SIGTERM

TIMEOUT_SLACK_TIME_SECONDS = 10


class Timeout(Tool):
    @property
    def command(self) -> str:
        return "timeout"

    @property
    def can_install(self) -> bool:
        return False

    def run_with_timeout(
        self,
        command: str,
        timeout: int,
        signal: int = SIGTERM,
        kill_timeout: int = 0,
    ) -> ExecutableResult:
        # timeout [OPTION] DURATION COMMAND [ARG]...

        # timeout exposes an option for a second timeout to force kill if
        # the initial signal fails to stop the process.
        # Select which timeout to base our LISA timeout on, then add some slack time
        # to allow the process to finish before LISA force kills.

        command_timeout = timeout
        if kill_timeout:
            command_timeout = kill_timeout
        command_timeout += TIMEOUT_SLACK_TIME_SECONDS

        return self.start_with_timeout(
            command=command,
            timeout=timeout,
            signal=signal,
            kill_timeout=kill_timeout,
        ).wait_result(timeout=command_timeout)

    def start_with_timeout(
        self,
        command: str,
        timeout: int,
        signal: int = SIGTERM,
        kill_timeout: int = 0,
        delay_start: int = 0,
    ) -> Process:
        # timeout [OPTION] DURATION COMMAND [ARG]...
        params = f"-s {signal} --preserve-status {timeout} {command}"
        if kill_timeout:
            params = f"--kill-after {kill_timeout} " + params
        return self.run_async(parameters=params, force_run=True, shell=True, sudo=True)
