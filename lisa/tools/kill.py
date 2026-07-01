# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.constants import SIGKILL

from .pgrep import Pgrep
from .pidof import Pidof


class Kill(Tool):
    @property
    def command(self) -> str:
        return "kill"

    @property
    def can_install(self) -> bool:
        return False

    def by_name(
        self, process_name: str, signum: int = SIGKILL, ignore_not_exist: bool = False
    ) -> None:
        # Find PIDs via pgrep (matches by process name), then kill each PID
        # individually to avoid the shell interpreting the name as a job spec.
        pgrep = self.node.tools[Pgrep]
        processes = pgrep.get_processes(process_name)
        if processes:
            for proc in processes:
                self.by_pid(proc.id, signum, ignore_not_exist)
            return

        # Fallback: try pidof in case pgrep missed it
        pids = self.node.tools[Pidof].get_pids(process_name, sudo=True)
        if pids:
            for pid in pids:
                self.by_pid(pid, signum, ignore_not_exist)
        else:
            self._log.debug(
                f"Kill for {process_name} did not find any processes to kill."
            )

    def by_pid(
        self, pid: str, signum: int = SIGKILL, ignore_not_exist: bool = False
    ) -> None:
        result = self.run(
            f"-{signum} {pid}",
            shell=True,
            sudo=True,
            force_run=True,
        )

        if result.exit_code != 0:
            if ignore_not_exist and "No such process" in result.stdout:
                self._log.debug(f"Kill for {pid} did not find any processes to kill.")
            else:
                raise LisaException(
                    f"failed to run {self.command} -{signum} {pid}: {result.stdout}"
                )
