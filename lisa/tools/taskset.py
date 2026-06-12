# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from typing import Optional, Type

from lisa.executable import Tool
from lisa.util.process import Process


class TaskSet(Tool):
    @property
    def command(self) -> str:
        return "taskset"

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return BSDTaskSet

    @property
    def can_install(self) -> bool:
        return False

    def run_on_specific_cpu(self, cpu_id: int) -> Process:
        return self.run_async(f"-c {cpu_id} yes > /dev/null", shell=True)

    def run_on_all_cpus_in_background(
        self,
        cpu_count: int,
        payload: str = "yes > /dev/null",
        seconds: int = 1,
        timeout: int = 60,
    ) -> None:
        # Pin one short-lived workload per CPU using a single SSH command.
        # Backgrounds (`&`) a `timeout`-bounded process per CPU, then `wait`s
        # for all of them.  This avoids opening one SSH channel per CPU,
        # which exhausts the paramiko transport on very large vCPU SKUs
        # (~300+) and is also faster end-to-end (~1s instead of N seconds).
        if cpu_count <= 1:
            return
        last_cpu = cpu_count - 1
        cmd = (
            f"for i in $(seq 1 {last_cpu}); do "
            f"{self.command} -c $i timeout {seconds} {payload} & "
            "done; wait"
        )
        self.node.execute(
            cmd,
            shell=True,
            sudo=False,
            no_debug_log=True,
            timeout=timeout,
        )


class BSDTaskSet(TaskSet):
    @property
    def command(self) -> str:
        return "cpuset"

    def run_on_specific_cpu(self, cpu_id: int) -> Process:
        return self.run_async(f"-l {cpu_id} yes > /dev/null", shell=True)

    def run_on_all_cpus_in_background(
        self,
        cpu_count: int,
        payload: str = "yes > /dev/null",
        seconds: int = 1,
        timeout: int = 60,
    ) -> None:
        # BSD lacks GNU `timeout`/`seq` and uses `cpuset -l` for CPU pinning.
        # BSD environments are unlikely to hit the very-high-vCPU SSH limit
        # that motivated the Linux fast path, so fall back to the legacy
        # per-CPU loop: spawn N background pinned workloads, sleep, kill.
        del payload, timeout  # not used on BSD; kept for API parity
        if cpu_count <= 1:
            return
        processes = [self.run_on_specific_cpu(i) for i in range(1, cpu_count)]
        try:
            time.sleep(seconds)
        finally:
            for proc in processes:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
