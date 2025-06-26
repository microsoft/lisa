# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Tuple

from lisa.executable import Tool
from lisa.tools import Lscpu
from lisa.util import LisaException


class NumaCtl(Tool):
    @property
    def command(self) -> str:
        return "numactl"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if hasattr(self.node.os, "install_packages"):
            self.node.os.install_packages(["numactl"])
            return True
        return False

    def get_best_numa_node(self) -> Tuple[int, str]:
        """
        Get the best NUMA node to use for binding by selecting the node
        with the most free memory to avoid hot/fragmented nodes.
        Returns tuple of (node_id, cpu_range_string).
        """
        lscpu = self.node.tools[Lscpu]
        numa_node_count = lscpu.get_numa_node_count()

        if numa_node_count <= 1:
            raise LisaException("System has only one NUMA node")

        # Select node with most free memory for better stability
        best_node = 0
        max_free_memory = 0

        for node_id in range(numa_node_count):
            try:
                result = self.node.execute(
                    f"cat /sys/devices/system/node/node{node_id}/meminfo",
                    shell=True,
                )
                if result.exit_code == 0:
                    # Parse MemFree from output
                    for line in result.stdout.split("\n"):
                        if "MemFree:" in line:
                            # Extract memory in kB
                            free_kb = int(line.split()[3])
                            if free_kb > max_free_memory:
                                max_free_memory = free_kb
                                best_node = node_id
                            break
            except Exception:
                # If we can't read meminfo for this node, skip it
                continue

        selected_node = best_node
        start_cpu, end_cpu = lscpu.get_cpu_range_in_numa_node(selected_node)
        cpu_range = f"{start_cpu}-{end_cpu}"

        return selected_node, cpu_range

    def bind_to_node(self, node_id: int, command: str) -> str:
        """
        Generate numactl command to bind both CPU and memory to a specific NUMA node.
        """
        # --cpunodebind binds CPUs from the specified node
        # --membind binds memory allocation to the specified node
        numa_prefix = f"{self.command} --cpunodebind={node_id} --membind={node_id}"

        if command.strip():
            return f"{numa_prefix} {command}"
        else:
            return numa_prefix
