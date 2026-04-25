# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.constants import SIGKILL

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
        pids = self.node.tools[Pidof].get_pids(process_name, sudo=True)
        for pid in pids:
            self.by_pid(pid, signum, ignore_not_exist)

        if not pids:
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
