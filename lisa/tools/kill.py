# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.executable import Tool

from .pidof import Pidof


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

        # attempt kill by name first
        kill_by_name = self.run(
            f"-s {signum} {process_name}", sudo=True, shell=True, force_run=True
        )
        if kill_by_name.exit_code == 0:
            return

        # fallback to kill by pid if first attempt fails for some reason
        pids = self.node.tools[Pidof].get_pids(process_name)
        for pid in pids:
            self.by_pid(pid, signum)
        else:
            self._log.debug(
                f"Kill for {process_name} did not find any processes to kill."
            )

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
