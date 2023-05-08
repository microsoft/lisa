from lisa.executable import ExecutableResult, Process, Tool
from lisa.util.constants import SIGTERM


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

        return self.start_with_timeout(
            command=command,
            timeout=timeout,
            signal=signal,
            kill_timeout=kill_timeout,
        ).wait_result()

    def start_with_timeout(
        self,
        command: str,
        timeout: int,
        signal: int = SIGTERM,
        kill_timeout: int = 0,
    ) -> Process:
        # timeout [OPTION] DURATION COMMAND [ARG]...
        params = f"-s {signal} --preserve-status {timeout} {command}"
        if kill_timeout:
            params = f"--kill-after {kill_timeout} " + params

        return self.run_async(
            parameters=params,
            shell=True,
            sudo=True,
        )
