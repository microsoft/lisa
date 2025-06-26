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
        Get the best NUMA node to use for binding.
        Returns tuple of (node_id, cpu_range_string).
        """
        lscpu = self.node.tools[Lscpu]
        numa_node_count = lscpu.get_numa_node_count()
        
        if numa_node_count <= 1:
            raise LisaException("System has only one NUMA node")
        
        # Use NUMA node 0 by default (could be enhanced to pick best one)
        selected_node = 0
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
