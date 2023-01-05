# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List

from lisa.executable import Tool
from lisa.util import find_patterns_in_lines


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
