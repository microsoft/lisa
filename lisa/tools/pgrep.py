# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List, Optional, Type

from lisa.executable import Tool
from lisa.util import find_groups_in_lines, find_patterns_in_lines


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
        output = self.run(
            f'-l "{process_identifier}"', sudo=True, force_run=True
        ).stdout
        found_processes = find_patterns_in_lines(output, [self._process_map_regex])
        running_process.extend(
            ProcessInfo(name=item[1], pid=item[0]) for item in found_processes[0]
        )
        return running_process


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
        output = self.run("-axceo user,pid,command", sudo=True, force_run=True).stdout
        found_processes = find_groups_in_lines(output, self._process_map_regex)
        running_process: List[ProcessInfo] = [
            ProcessInfo(name=item["name"], pid=item["id"])
            for item in found_processes
            if process_identifier in item["name"]
        ]
        return running_process
