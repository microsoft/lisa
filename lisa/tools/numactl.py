# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Optional, Tuple

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

    def get_best_numa_node(
        self, preferred_node: Optional[int] = None
    ) -> Tuple[int, str]:
        """
        Get the best NUMA node to use for binding.

        Selection strategy:
        1. If preferred_node is provided and has sufficient memory, use it
        2. Otherwise, select the node with the most free memory

        Args:
            preferred_node: Preferred NUMA node (e.g., device locality)

        Returns:
            Tuple of (node_id, cpu_range_string)
        """
        lscpu = self.node.tools[Lscpu]
        numa_node_count = lscpu.get_numa_node_count()

        if numa_node_count <= 1:
            raise LisaException("System has only one NUMA node")

        # Collect free memory for all nodes
        node_memory: dict[int, int] = {}
        for node_id in range(numa_node_count):
            try:
                result = self.node.execute(
                    f"cat /sys/devices/system/node/node{node_id}/meminfo",
                    shell=True,
                )
                if result.exit_code == 0:
                    for line in result.stdout.split("\n"):
                        if "MemFree:" in line:
                            free_kb = int(line.split()[3])
                            node_memory[node_id] = free_kb
                            break
            except Exception:
                continue

        if not node_memory:
            raise LisaException("Could not determine free memory for any NUMA node")

        # Select node with strategy
        selected_node = 0

        if preferred_node is not None and preferred_node in node_memory:
            # Use preferred node if it has > 10% of max free memory
            max_free = max(node_memory.values())
            preferred_free = node_memory[preferred_node]

            if preferred_free > max_free * 0.1:  # At least 10% of max
                selected_node = preferred_node
                self._log.debug(
                    f"Using preferred NUMA node {preferred_node} "
                    f"(free={preferred_free}KB, max={max_free}KB)"
                )
            else:
                # Preferred node too fragmented, use best available
                selected_node = max(node_memory, key=node_memory.get)  # type: ignore
                self._log.debug(
                    f"Preferred node {preferred_node} has low memory "
                    f"({preferred_free}KB), using node {selected_node} instead"
                )
        else:
            # No preference or invalid node, use node with most free memory
            selected_node = max(node_memory, key=node_memory.get)  # type: ignore

        start_cpu, end_cpu = lscpu.get_cpu_range_in_numa_node(selected_node)
        cpu_range = f"{start_cpu}-{end_cpu}"

        return selected_node, cpu_range

    def bind_to_node(self, node_id: int, command: str) -> str:
        """
        Generate numactl command for strict binding (CPU + memory to one node).
        """
        # --cpunodebind binds CPUs from the specified node
        # --membind binds memory allocation to the specified node
        numa_prefix = f"{self.command} --cpunodebind={node_id} --membind={node_id}"

        if command.strip():
            return f"{numa_prefix} {command}"
        else:
            return numa_prefix

    def bind_interleave(self, command: str = "") -> str:
        """
        Generate numactl command for interleaved memory policy across all nodes.
        This is better for multi-queue workloads that span multiple NUMA nodes.
        """
        numa_prefix = f"{self.command} --interleave=all"

        if command.strip():
            return f"{numa_prefix} {command}"
        else:
            return numa_prefix
