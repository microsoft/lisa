# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.util.process import Process


class TaskSet(Tool):
    @property
    def command(self) -> str:
        return "taskset"

    @property
    def can_install(self) -> bool:
        return False

    def run_on_specific_cpu(self, cpu_id: int) -> Process:
        return self.run_async(f"-c {cpu_id} yes > /dev/null", shell=True)
