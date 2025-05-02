import time
from typing import List, cast

from lisa.executable import Tool
from lisa.operating_system import FreeBSD, Posix
from lisa.util import LisaException, create_timer


class Pidof(Tool):
    @property
    def command(self) -> str:
        return "pidof"

    @property
    def can_install(self) -> bool:
        if isinstance(self.node.os, FreeBSD):
            return True
        else:
            return False

    def get_pids(self, process_name: str, sudo: bool = False) -> List[str]:
        pids = []
        # it's fine to fail
        result = self.run(process_name, force_run=True, shell=True, sudo=sudo)
        if result.exit_code == 0:
            pids = [x.strip() for x in result.stdout.split(" ")]
        return pids

    def wait_processes(
        self, process_name: str, timeout: int = 600, interval: int = 10
    ) -> None:
        start_timer = create_timer()
        pid = self.node.tools[Pidof]
        while start_timer.elapsed(False) < timeout:
            # Check if the process is still running. For example, the WSL
            # doesn't support process operations, so it needs to check the
            # process status by pgrep.
            #
            # The long running process may timeout on SSH connection. This
            # check is also help keep SSH alive.
            process_infos = pid.get_pids(process_name)
            if not process_infos:
                self._log.debug(
                    f"The '{process_name}' process is not running, stop to wait."
                )
                break
            time.sleep(interval)

        if start_timer.elapsed(False) >= timeout:
            raise LisaException(
                f"The '{process_name}' process timed out with {timeout} seconds."
            )

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("pidof")
        return self._check_exists()
