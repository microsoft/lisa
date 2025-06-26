# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, Optional

from lisa import Logger, Node
from lisa.tools import Lscpu, NumaCtl, TaskSet
from lisa.util import LisaException


class NumaTestMixin:
    """
    Mixin class to provide NUMA affinity functionality for test suites.
    
    This mixin helps ensure that tests run with CPU and memory affinity
    to the same NUMA node, which is especially important on large Azure VMs
    with multiple NUMA nodes to get consistent performance results.
    """

    def setup_numa_affinity(
        self,
        node: Node,
        log: Logger,
        preferred_numa_node: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Set up NUMA affinity for test execution.
        
        Args:
            node: The node to configure NUMA affinity on
            log: Logger instance
            preferred_numa_node: Specific NUMA node to use, or None for auto-selection
            
        Returns:
            Dictionary containing NUMA configuration information
        """
        numa_info = self._initialize_numa_info()
        
        try:
            lscpu = node.tools[Lscpu]
            numa_node_count = lscpu.get_numa_node_count()
            numa_info["numa_node_count"] = numa_node_count
            
            log.info(f"Detected {numa_node_count} NUMA nodes")
            
            if numa_node_count <= 1:
                log.info("Single NUMA node system - no NUMA binding needed")
                return numa_info
            
            numa_tool = self._setup_numa_tool(node, log, numa_info)
            if numa_tool is None:
                return numa_info
            
            selected_node, cpu_range = self._select_numa_node(
                lscpu, numa_tool, numa_info, preferred_numa_node, numa_node_count
            )
            
            self._configure_binding(numa_info, numa_tool, selected_node, cpu_range)
            
            log.info(
                f"NUMA affinity configured: node={selected_node}, "
                f"cpu_range={cpu_range}, tool={numa_info['numa_tool']}"
            )
            
            self._log_numa_topology(numa_tool, numa_info, log)
            
        except Exception as e:
            log.warning(f"Failed to setup NUMA affinity: {e}")
            
        return numa_info
    
    def _initialize_numa_info(self) -> Dict[str, Any]:
        """Initialize NUMA configuration dictionary."""
        return {
            "numa_enabled": False,
            "numa_node_count": 1,
            "selected_numa_node": 0,
            "cpu_range": "0",
            "bind_command_prefix": "",
            "numa_tool": "none"
        }
    
    def _setup_numa_tool(
        self, node: Node, log: Logger, numa_info: Dict[str, Any]
    ) -> Optional[Any]:
        """Setup NUMA binding tool (numactl or taskset)."""
        try:
            numa_tool = node.tools[NumaCtl]
            if not numa_tool._check_exists():
                numa_tool._install()
            numa_info["numa_tool"] = "numactl"
            log.info("Using numactl for NUMA binding")
            return numa_tool
        except Exception as e:
            log.debug(f"numactl not available: {e}")
            try:
                numa_tool = node.tools[TaskSet]
                numa_info["numa_tool"] = "taskset"
                log.info("Using taskset for CPU affinity (memory not bound)")
                return numa_tool
            except Exception as e2:
                log.warning(f"No NUMA binding tools available: {e2}")
                return None
    
    def _select_numa_node(
        self,
        lscpu: Any,
        numa_tool: Any,
        numa_info: Dict[str, Any],
        preferred_numa_node: Optional[int],
        numa_node_count: int
    ) -> tuple:
        """Select the NUMA node to use and get CPU range."""
        if preferred_numa_node is not None:
            if preferred_numa_node >= numa_node_count:
                raise LisaException(
                    f"Preferred NUMA node {preferred_numa_node} not available. "
                    f"System has {numa_node_count} nodes (0-{numa_node_count - 1})"
                )
            selected_node = preferred_numa_node
            start_cpu, end_cpu = lscpu.get_cpu_range_in_numa_node(selected_node)
            cpu_range = f"{start_cpu}-{end_cpu}"
        else:
            # Auto-select the best NUMA node
            if numa_info["numa_tool"] == "numactl":
                selected_node, cpu_range = numa_tool.get_best_numa_node()
            else:
                # Using taskset, just get NUMA node 0 range
                selected_node = 0
                start_cpu, end_cpu = lscpu.get_cpu_range_in_numa_node(0)
                cpu_range = f"{start_cpu}-{end_cpu}"
        
        return selected_node, cpu_range
      def _configure_binding(
        self,
        numa_info: Dict[str, Any],
        numa_tool: Any,
        selected_node: int,
        cpu_range: str
    ) -> None:
        """Configure the binding command prefix."""
        numa_info["selected_numa_node"] = selected_node
        numa_info["cpu_range"] = cpu_range
        numa_info["numa_enabled"] = True
        
        # Create the command prefix for binding
        if numa_info["numa_tool"] == "numactl":
            numa_info["bind_command_prefix"] = numa_tool.bind_to_node(
                selected_node, ""
            ).rstrip()
        else:
            # TaskSet only binds CPUs, not memory
            numa_info["bind_command_prefix"] = f"{numa_tool.command} -c {cpu_range}"
    
    def _log_numa_topology(self, numa_tool: Any, numa_info: Dict[str, Any], log: Logger) -> None:
        """Log NUMA topology information for debugging."""
        if numa_info["numa_tool"] == "numactl":
            try:
                topology = numa_tool.get_hardware_info()
                log.debug(f"NUMA topology:\n{topology}")
            except Exception as e:
                log.debug(f"Failed to get NUMA topology: {e}")
    
    def execute_with_numa_binding(
        self, 
        node: Node, 
        command: str, 
        numa_info: Dict[str, Any],
        **kwargs: Any
    ) -> Any:
        """
        Execute a command with NUMA binding if enabled.
        
        Args:
            node: The node to execute the command on
            command: The command to execute
            numa_info: NUMA configuration from setup_numa_affinity()
            **kwargs: Additional arguments to pass to node.execute()
            
        Returns:
            Result of command execution
        """
        if numa_info["numa_enabled"] and numa_info["bind_command_prefix"]:
            bound_command = f"{numa_info['bind_command_prefix']} {command}"
            node.log.debug(f"Executing with NUMA binding: {bound_command}")
            return node.execute(bound_command, **kwargs)
        else:
            return node.execute(command, **kwargs)
    
    def log_numa_status(self, node: Node, numa_info: Dict[str, Any], log: Logger) -> None:
        """
        Log the current NUMA status and configuration.
        
        Args:
            node: The node
            numa_info: NUMA configuration information
            log: Logger instance
        """
        log.info("NUMA Configuration Status:")
        log.info(f"  NUMA Enabled: {numa_info['numa_enabled']}")
        log.info(f"  NUMA Nodes: {numa_info['numa_node_count']}")
        log.info(f"  Selected Node: {numa_info['selected_numa_node']}")
        log.info(f"  CPU Range: {numa_info['cpu_range']}")
        log.info(f"  Binding Tool: {numa_info['numa_tool']}")
        
        if numa_info["numa_enabled"]:
            try:
                # Get current memory info from the selected NUMA node
                if numa_info["numa_tool"] == "numactl":
                    numa_tool = node.tools[NumaCtl]
                    policy = numa_tool.get_numa_policy()
                    log.debug(f"Current NUMA policy: {policy}")
            except Exception as e:
                log.debug(f"Failed to get NUMA policy: {e}")
    
    def get_numa_node_memory_info(self, node: Node, numa_node: int) -> Dict[str, Any]:
        """
        Get memory information for a specific NUMA node.
        
        Args:
            node: The node
            numa_node: NUMA node ID
            
        Returns:
            Dictionary with memory information
        """
        memory_info = {
            "numa_node": numa_node,
            "total_memory_mb": 0,
            "free_memory_mb": 0,
            "available": True
        }
        
        try:
            # Try to get NUMA-specific memory info
            result = node.execute(
                f"cat /sys/devices/system/node/node{numa_node}/meminfo",
                force_run=True
            )
            
            for line in result.stdout.split('\n'):
                if 'MemTotal:' in line:
                    # Extract memory in kB and convert to MB
                    memory_kb = int(line.split()[3])
                    memory_info["total_memory_mb"] = memory_kb // 1024
                elif 'MemFree:' in line:
                    memory_kb = int(line.split()[3])
                    memory_info["free_memory_mb"] = memory_kb // 1024
                    
        except Exception as e:
            node.log.debug(f"Failed to get NUMA node {numa_node} memory info: {e}")
            memory_info["available"] = False
            
        return memory_info
    
    def validate_numa_binding(
        self, 
        node: Node, 
        numa_info: Dict[str, Any], 
        log: Logger
    ) -> bool:
        """
        Validate that NUMA binding is working as expected.
        
        Args:
            node: The node
            numa_info: NUMA configuration information
            log: Logger instance
            
        Returns:
            True if validation passes, False otherwise
        """
        if not numa_info["numa_enabled"]:
            log.info("NUMA binding not enabled - validation skipped")
            return True
            
        try:
            # Test that we can execute a command with NUMA binding
            test_command = "echo 'NUMA binding test'"
            result = self.execute_with_numa_binding(node, test_command, numa_info)
            
            if result.exit_code != 0:
                log.warning(f"NUMA binding test failed: {result.stderr}")
                return False
                
            log.info("NUMA binding validation passed")
            return True
            
        except Exception as e:
            log.warning(f"NUMA binding validation failed: {e}")
            return False
