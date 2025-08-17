# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from enum import Enum
from typing import Any, List, Optional, Tuple, Type
from xml import etree

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import CpuArchitecture, FreeBSD, Posix
from lisa.tools.powershell import PowerShell
from lisa.util import LisaException, find_group_in_lines, find_groups_in_lines

CpuType = Enum(
    "CpuType",
    ["AMD", "Intel", "ARM"],
)


class CPUInfo:
    def __init__(
        self,
        cpu: int,
        numa_node: int,
        socket: int,
        l1_data_cache: int,
        l1_instruction_cache: int,
        l2_cache: int,
        l3_cache: int,
    ) -> None:
        self.cpu = cpu
        self.numa_node = numa_node
        self.socket = socket
        self.l1_data_cache = l1_data_cache
        self.l1_instruction_cache = l1_instruction_cache
        self.l2_cache = l2_cache
        self.l3_cache = l3_cache

    def __str__(self) -> str:
        return (
            f"cpu : {self.cpu}, "
            f"numa_node : {self.numa_node}, "
            f"socket : {self.socket}, "
            f"l1_data_cache : , {self.l1_data_cache}, "
            f"l1_instruction_cache : {self.l1_instruction_cache}, "
            f"l2_cache : {self.l2_cache}, "
            f"l3_cache : {self.l3_cache}"
        )

    def __repr__(self) -> str:
        return self.__str__()


ArchitectureNames = {
    "x86_64": CpuArchitecture.X64,
    "aarch64": CpuArchitecture.ARM64,
    "amd64": CpuArchitecture.X64,
    "arm64": CpuArchitecture.ARM64,
}


class Lscpu(Tool):
    # Positive example:
    # CPU(s):              16
    # Total CPU(s):            2
    # Negative example:
    # NUMA node0 CPU(s):               0
    __vcpu = re.compile(r"^(CPU|Total CPU)\(s\):[ ]+([\d]+)\r?$", re.M)
    # Thread(s) per core:  1
    #      Thread(s) per core:  1
    __thread_per_core = re.compile(r"^[ ]*Thread\(s\) per core:[ ]+([\d]+)\r?$", re.M)
    # Core(s) per socket:  8
    #     Core(s) per socket:  2
    __core_per_socket = re.compile(r"^[ ]*Core\(s\) per socket:[ ]+([\d]+)\r?$", re.M)
    # Core(s) per cluster: 16
    __core_per_cluster = re.compile(r"^Core\(s\) per cluster:[ ]+([\d]+)\r?$", re.M)
    # Socket(s):           2
    #     Socket(s):           1
    __sockets = re.compile(r"^[ ]*Socket\(s\):[ ]+([\d]+)\r?$", re.M)
    # Cluster(s):          1
    __clusters = re.compile(r"^Cluster\(s\):[ ]+([\d]+)\r?$", re.M)
    # Architecture:        x86_64
    __architecture_pattern = re.compile(r"^Architecture:\s+(.*)?\r$", re.M)

    # 0 0 0 0:0:0:0
    # 96 0 10 1:1:1:0
    _core_numa_mappings = re.compile(
        r"\s*(?P<cpu>\d+)\s+(?P<numa_node>\d+)\s+(?P<socket>\d+)\s+"
        r"(?P<l1_data_cache>\d+):(?P<l1_instruction_cache>\d+):"
        r"(?P<l2_cache>\d+):(?P<l3_cache>\d+)$"
    )
    # Model name:          Intel(R) Xeon(R) Platinum 8168 CPU @ 2.70GHz
    # Model name:          AMD EPYC 7763 64-Core Processor
    #   Model name:          AMD EPYC 7763 64-Core Processor
    __cpu_model_name = re.compile(r"^\s*Model name:\s+(?P<model_name>.*)\s*$", re.M)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._thread_count: Optional[int] = None

    @property
    def command(self) -> str:
        return "lscpu"

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsLscpu

    @classmethod
    def _vmware_esxi_tool(cls) -> Optional[Type[Tool]]:
        return VMWareESXiLscpu

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return BSDLscpu

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, FreeBSD):
            self.node.os.install_packages("lscpu")
        elif isinstance(self.node.os, Posix):
            self.node.os.install_packages("util-linux")
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        return self._check_exists()

    def get_core_count(self, force_run: bool = False) -> int:
        """
        Return the number of physical cores on the system.
        Physical cores = Core(s) per socket * Socket(s).
        """
        core_per_socket = self.get_core_per_socket_count(force_run=force_run)
        socket_count = self.get_socket_count(force_run=force_run)
        physical_core_count = core_per_socket * socket_count

        return physical_core_count

    def get_architecture(self, force_run: bool = False) -> CpuArchitecture:
        architecture: str = ""
        result = self.run(force_run=force_run)
        matched = self.__architecture_pattern.findall(result.stdout)
        assert_that(
            matched,
            f"architecture should have exact one line, but got {matched}",
        ).is_length(1)
        architecture = matched[0]
        assert_that(
            [architecture],
            f"architecture {architecture} must be one of "
            f"{ArchitectureNames.keys()}.",
        ).is_subset_of(ArchitectureNames.keys())
        return ArchitectureNames[architecture]

    def get_thread_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__vcpu.findall(result.stdout)
        assert_that(
            len(matched),
            f"cpu count should have exact one line, but got {matched}",
        ).is_equal_to(1)
        self._thread_count = int(matched[0][1])

        return self._thread_count

    def get_thread_per_core_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__thread_per_core.findall(result.stdout)
        assert_that(
            len(matched),
            f"thread per core count should have exact one line, but got {matched}",
        ).is_equal_to(1)

        return int(matched[0])

    def get_core_per_socket_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__core_per_socket.findall(result.stdout)
        assert_that(
            len(matched),
            f"core per socket count should have exact one line, but got {matched}",
        ).is_equal_to(1)

        return int(matched[0])

    def get_core_per_cluster_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__core_per_cluster.findall(result.stdout)
        assert_that(
            len(matched),
            f"core per cluster count should have exact one line, but got {matched}",
        ).is_equal_to(1)

        return int(matched[0])

    def get_socket_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__sockets.findall(result.stdout)
        assert_that(
            len(matched),
            f"socket count should have exact one line, but got {matched}",
        ).is_equal_to(1)

        return int(matched[0])

    def get_cluster_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__clusters.findall(result.stdout)
        assert_that(
            len(matched),
            f"cluster count should have exact one line, but got {matched}",
        ).is_equal_to(1)

        return int(matched[0])

    def calculate_vcpu_count(self, force_run: bool = False) -> int:
        # The concept of a "cluster" of CPUs was recently added in the Linux
        # 5.16 kernel in commit c5e22feffdd7. There is "Core(s) per cluster"
        # and "Cluster(s)" in the output of lscpu. If there is cluster topology,
        # calculate vCPU count by core_per_cluster_count * cluster_count *
        # thread_per_core_count, else by core_per_socket_count * socket_count *
        # thread_per_core_count.
        result = self.run(force_run=force_run)
        if "Core(s) per cluster" in result.stdout:
            calculated_cpu_count = (
                self.get_core_per_cluster_count()
                * self.get_cluster_count()
                * self.get_thread_per_core_count()
            )
        else:
            calculated_cpu_count = (
                self.get_core_per_socket_count()
                * self.get_socket_count()
                * self.get_thread_per_core_count()
            )
        return calculated_cpu_count

    def get_cpu_type(self, force_run: bool = False) -> CpuType:
        result = self.run(force_run=force_run)
        if "AuthenticAMD" in result.stdout:
            return CpuType.AMD
        elif "GenuineIntel" in result.stdout:
            return CpuType.Intel
        elif "ARM" in result.stdout or "aarch64" in result.stdout:
            return CpuType.ARM
        else:
            raise LisaException(
                f"Unknow cpu type. The output of lscpu is {result.stdout}"
            )

    def get_cpu_model_name(self, force_run: bool = False) -> Optional[str]:
        result = self.run(force_run=force_run)
        matched = self.__cpu_model_name.findall(result.stdout)
        if len(matched) == 0:
            return None

        return str(matched[0])

    def get_cpu_info(self) -> List[CPUInfo]:
        # `lscpu --extended=cpu,node,socket,cache` command return the
        # cpu info in the format :
        # CPU NODE SOCKET L1d:L1i:L2:L3
        # 0    0        0 0:0:0:0
        # 1    0        0 0:0:0:0
        result = self.run(
            "--extended=cpu,node,socket,cache", expected_exit_code=0
        ).stdout
        mappings_with_header = result.splitlines(keepends=False)
        mappings = mappings_with_header[1:]
        assert_that(mappings).described_as(
            f"lscpu output should contain atleast one entry, but got {mappings}"
        ).is_not_empty()
        output: List[CPUInfo] = []
        for item in mappings:
            match_result = self._core_numa_mappings.fullmatch(item)
            assert (
                match_result
            ), f"lscpu NUMA node mapping is not in expected format: {item}"
            output.append(
                CPUInfo(
                    cpu=int(match_result.group("cpu")),
                    numa_node=int(match_result.group("numa_node")),
                    socket=int(match_result.group("socket")),
                    l1_data_cache=int(match_result.group("l1_data_cache")),
                    l1_instruction_cache=int(
                        match_result.group("l1_instruction_cache")
                    ),
                    l2_cache=int(match_result.group("l2_cache")),
                    l3_cache=int(match_result.group("l3_cache")),
                )
            )
        return output

    def get_numa_node_count(self) -> int:
        # get count of numa nodes on the machine, add 1 to account
        # for 0 indexing
        return max([int(cpu.numa_node) for cpu in self.get_cpu_info()]) + 1

    def get_cpu_range_in_numa_node(self, numa_node_index: int = 0) -> Tuple[int, int]:
        cpus = self.get_cpu_info()
        cpu_indexes = [cpu.cpu for cpu in cpus if cpu.numa_node == numa_node_index]
        return min(cpu_indexes), max(cpu_indexes)

    def is_virtualization_enabled(self) -> bool:
        result = self.run(sudo=True).stdout
        if ("VT-x" in result) or ("AMD-V" in result):
            return True
        return False


class WindowsLscpu(Lscpu):
    # Processor(s):              1 Processor(s) Installed.
    __cpu_count = re.compile(
        r"^Processor\(s\):\s+(?P<count>[\d]+) Processor\(s\) Installed.\r?$", re.M
    )
    # NumberOfProcessors          : 1
    __number_of_processors = re.compile(
        r"^NumberOfProcessors\s+:\s+(?P<count>\d+)$", re.M
    )
    # NumberOfLogicalProcessors   : 12
    __number_of_logic_processors = re.compile(
        r"^NumberOfLogicalProcessors\s+:\s+(?P<count>\d+)$", re.M
    )

    __computer_system_command = "Get-CimInstance Win32_ComputerSystem | fl *"

    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    def get_thread_count(self, force_run: bool = False) -> int:
        result = self.node.tools[PowerShell].run_cmdlet(
            self.__computer_system_command, force_run=force_run
        )
        # Linux returns vCPU count, so let Windows return vCPU count too.
        thread_count = int(
            find_group_in_lines(result, self.__number_of_logic_processors)["count"]
        )
        self._log.debug(f"vCPU thread count: {thread_count}")
        return thread_count

    def get_socket_count(self, force_run: bool = False) -> int:
        result = self.node.tools[PowerShell].run_cmdlet(
            "systeminfo", force_run=force_run
        )
        socket_count = int(find_group_in_lines(result, self.__cpu_count)["count"])
        self._log.debug(f"socket count: {socket_count}")
        return socket_count

    def get_core_per_socket_count(self, force_run: bool = False) -> int:
        socket_count = self.get_socket_count(force_run=force_run)
        core_count = self._get_core_count(force_run=force_run)
        core_pre_socket = core_count // socket_count
        self._log.debug(f"core per socket: {core_pre_socket}")

        return core_pre_socket

    def get_thread_per_core_count(self, force_run: bool = False) -> int:
        physical_core_count = self._get_core_count(force_run=force_run)
        thread_count = self.get_thread_count(force_run=force_run)

        thread_per_core = thread_count // physical_core_count
        self._log.debug(f"thread per core: {thread_per_core}")
        return thread_per_core

    def _get_core_count(self, force_run: bool = False) -> int:
        result = self.node.tools[PowerShell].run_cmdlet(
            self.__computer_system_command, force_run=force_run
        )
        core_count = int(
            find_group_in_lines(result, self.__number_of_processors)["count"]
        )
        self._log.debug(f"physical core count: {core_count}")
        return core_count


class BSDLscpu(Lscpu):
    # FreeBSD/SMP: 1 package(s) x 4 core(s) x 2 hardware threads
    __cpu_info = re.compile(r"FreeBSD/SMP: (?P<package_count>\d+) package\(s\) .*")

    @property
    def command(self) -> str:
        return "sysctl"

    def get_thread_count(self, force_run: bool = False) -> int:
        output = self.run("-n kern.smp.cpus", force_run=force_run)
        core_count = int(output.stdout.strip())
        return core_count

    def get_architecture(self, force_run: bool = False) -> CpuArchitecture:
        architecture = self.run(
            "-n hw.machine_arch", force_run=force_run
        ).stdout.strip()
        assert_that(
            [architecture],
            f"architecture {architecture} must be one of "
            f"{ArchitectureNames.keys()}.",
        ).is_subset_of(ArchitectureNames.keys())
        return ArchitectureNames[architecture]

    def get_cluster_count(self, force_run: bool = False) -> int:
        output = self.run(
            "-a | grep -i 'package(s)'",
            force_run=force_run,
            shell=True,
        )

        if output.exit_code == 0:
            matched = find_groups_in_lines(output.stdout.strip(), self.__cpu_info)
            assert matched[0], "core_per_cluster_count is not set"
            return int(matched[0]["package_count"])
        else:
            results = self.run(
                "-n kern.sched.topology_spec",
                force_run=force_run,
                expected_exit_code=0,
                expected_exit_code_failure_message="kern.sched.topology_spec isn't set",
            ).stdout.strip()
            topology_spec = etree.ElementTree.fromstring(results)
            return len(topology_spec.findall(".//group"))

    def get_core_per_cluster_count(self, force_run: bool = False) -> int:
        output = self.run(
            "-n kern.smp.cores",
            force_run=force_run,
            expected_exit_code=0,
            expected_exit_code_failure_message="kern.smp.cores is not set",
        ).stdout.strip()

        return int(output)

    def get_thread_per_core_count(self, force_run: bool = False) -> int:
        threads_per_core = self.run(
            "-n kern.smp.threads_per_core",
            force_run=force_run,
            expected_exit_code=0,
            expected_exit_code_failure_message="kern.smp.threads_per_core is not set",
        ).stdout.strip()

        return int(threads_per_core)

    def calculate_vcpu_count(self, force_run: bool = False) -> int:
        return (
            self.get_core_per_cluster_count()
            * self.get_cluster_count()
            * self.get_thread_per_core_count()
        )

    def get_cpu_type(self, force_run: bool = False) -> CpuType:
        result = self.run("-n hw.model", force_run=force_run).stdout.strip()
        if "AMD" in result:
            return CpuType.AMD
        elif "Intel" in result:
            return CpuType.Intel
        elif "ARM" in result or "aarch64" in result:
            return CpuType.ARM
        else:
            raise LisaException(f"Unknow cpu type. The output of lscpu is {result}")


class VMWareESXiLscpu(Lscpu):
    #    CPU Threads: 208
    __cpu_threads = re.compile(r"CPU Threads:[ ]+([\d]+)?", re.M)
    #    CPU Packages: 2
    __cpu_packages = re.compile(r"CPU Packages:[ ]+([\d]+)?", re.M)
    #    CPU Cores: 104
    __cpu_cores = re.compile(r"CPU Cores:[ ]+([\d]+)?", re.M)

    @property
    def command(self) -> str:
        return "esxcli"

    def get_thread_count(self, force_run: bool = False) -> int:
        result = self.run("hardware cpu global get", force_run)
        matched = self.__cpu_threads.findall(result.stdout)
        assert_that(
            len(matched),
            f"cpu thread should have exact one line, but got {matched}",
        ).is_equal_to(1)
        self._thread_count = int(matched[0])
        return self._thread_count

    def calculate_vcpu_count(self, force_run: bool = False) -> int:
        result = self.run("hardware cpu global get", force_run)
        matched_cpu_packages = self.__cpu_packages.findall(result.stdout)
        assert_that(
            len(matched_cpu_packages),
            f"cpu packages should have exact one line, but got {matched_cpu_packages}",
        ).is_equal_to(1)
        matched_cpu_cores = self.__cpu_cores.findall(result.stdout)
        assert_that(
            len(matched_cpu_cores),
            f"cpu cores should have exact one line, but got {matched_cpu_cores}",
        ).is_equal_to(1)
        return int(matched_cpu_packages[0]) * int(matched_cpu_cores[0])
