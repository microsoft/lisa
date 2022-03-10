# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool

from .pgrep import Pgrep


class Kill(Tool):

    SIGINT = 2
    SIGTERM = 15
    SIGKILL = 9

    @property
    def command(self) -> str:
        return "kill"

    @property
    def can_install(self) -> bool:
        return False

    def by_name(self, process_name: str, signum: int = SIGKILL) -> None:
        running_processes = self.node.tools[Pgrep].get_processes(process_name)
        for process in running_processes:
            self.by_pid(process.id, signum)

    def by_pid(self, pid: str, signum: int = SIGKILL) -> None:
        self.run(
            f"-{signum} {pid}",
            shell=True,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run "
            f"{self.command} -{signum} {pid}",
        )
