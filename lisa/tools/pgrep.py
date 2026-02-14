# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from typing import List, Optional, Type

from lisa.executable import Tool
from lisa.util import (
    LisaException,
    create_timer,
    find_groups_in_lines,
    find_patterns_in_lines,
)

# WSL error patterns that indicate connection issues, not process absence
_WSL_ERROR_PATTERNS = [
    "HCS_E_CONNECTION_TIMEOUT",
    "E_UNEXPECTED",
    "Catastrophic failure",
]


class ProcessInfo(object):
    def __init__(self, name: str, pid: str) -> None:
        self.name = name
        self.id = pid

    def __repr__(self) -> str:
        return f"name: {self.name}, id: {self.id}"

    def __str__(self) -> str:
        return self.__repr__()


class Pgrep(Tool):
    # 500 python
    _process_map_regex = re.compile(r"^(?P<id>\d+)\s+(?P<name>\S+)\s*$", re.M)

    @property
    def command(self) -> str:
        return "pgrep"

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return PsBSD

    @property
    def can_install(self) -> bool:
        return False

    def get_processes(self, process_identifier: str) -> List[ProcessInfo]:
        running_process: List[ProcessInfo] = []
        result = self.run(f'-l "{process_identifier}"', sudo=True, force_run=True)

        # Check for WSL connection errors before processing
        if any(err in result.stdout for err in _WSL_ERROR_PATTERNS):
            raise LisaException(
                f"WSL error while checking process '{process_identifier}': "
                f"{result.stdout}"
            )

        output = result.stdout
        found_processes = find_patterns_in_lines(output, [self._process_map_regex])
        running_process.extend(
            ProcessInfo(name=item[1], pid=item[0]) for item in found_processes[0]
        )
        return running_process

    def wait_processes(
        self, process_name: str, timeout: int = 600, interval: int = 10
    ) -> None:
        start_timer = create_timer()
        pgrep = self.node.tools[Pgrep]
        while start_timer.elapsed(False) < timeout:
            # Check if the process is still running. For example, the WSL
            # doesn't support process operations, so it needs to check the
            # process status by pgrep.
            #
            # The long running process may timeout on SSH connection. This
            # check is also help keep SSH alive.
            process_infos = pgrep.get_processes(process_name)
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


class PsBSD(Pgrep):
    # Example output:
    # USER       PID COMMAND
    # root         0 kernel
    # root         1 init
    _process_map_regex = re.compile(
        r"^(?P<user>\S+)\s+(?P<id>\d+)\s+(?P<name>\S+)\s*$", re.M
    )

    @property
    def command(self) -> str:
        return "ps"

    def get_processes(self, process_identifier: str) -> List[ProcessInfo]:
        result = self.run("-axceo user,pid,command", sudo=True, force_run=True)

        # Check for WSL connection errors before processing
        if any(err in result.stdout for err in _WSL_ERROR_PATTERNS):
            raise LisaException(
                f"WSL error while checking process '{process_identifier}': "
                f"{result.stdout}"
            )

        output = result.stdout
        found_processes = find_groups_in_lines(output, self._process_map_regex)
        running_process: List[ProcessInfo] = [
            ProcessInfo(name=item["name"], pid=item["id"])
            for item in found_processes
            if process_identifier in item["name"]
        ]
        return running_process
