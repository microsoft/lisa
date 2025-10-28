import re
from typing import TYPE_CHECKING, Optional, Tuple, Type, cast
from urllib.parse import urlparse

from assertpy.assertpy import assert_that
from retry import retry

from lisa.base_tools import Cat
from lisa.executable import Tool
from lisa.tools.ls import Ls
from lisa.tools.mkdir import Mkdir
from lisa.tools.powershell import PowerShell
from lisa.tools.rm import Rm
from lisa.util import LisaException, LisaTimeoutException, is_valid_url
from lisa.util.process import ExecutableResult

if TYPE_CHECKING:
    from lisa.operating_system import Posix


class Numactl(Tool):
    # numactl -H
    # available: 3 nodes (0-2)
    # ....
    # node 2 cpus: 
    # node 2 size: 64510 MB
    # node 2 free: 64461 MB
    # ....
    __cxl_node=re.compile(r"node (\d+) cpus:\s*$", re.MULTILINE)
    # numactl -H
    # available: 3 nodes (0-2)
    # node 0 cpus: 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15
    # node 0 size: 32133 MB
    # node 0 free: 31637 MB
    # node 1 cpus: 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31
    # node 1 size: 32251 MB
    # node 1 free: 31815 MB
    # ....
    __numa_nodes=re.compile(r"node (\d+) cpus:(?:\s*\d+)+", re.MULTILINE)
    # sysbench 1.0.20
    # Running the test with following options:
    # ......
    # 8192.00MiB transferred (183.53 MiB/sec)
    # ......
    # General statistis:
    #    total time:     44.6566s
    # ......
    __avg_speed=re.compile(r"(\d+\.\d+) MiB/sec")
    __total_time = re.compile(r"total time:\s+(\d+\.\d+)s")
    
    @property
    def command(self) -> str:
        return "numactl"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("numactl")
        return self._check_exists()

    def help(self) -> ExecutableResult:
        return self.run("-H")

    def _run_command(self,command: str) -> ExecutableResult:
        return self.node.execute(f"{command} --version", shell=True)

    def _is_installed(self,command: str) -> bool:
        result = self._run_command(command)
        return result.exit_code == 0

    def get_cxl_node(self) -> int:
        output = self.help()
        match = self.__cxl_node.findall(output.stdout)

        assert_that(len(match),"CXL node is not present").is_greater_than(0)
        return match[0]
    
    def get_numa_nodes(self):
        output = self.help()
        match = self.__numa_nodes.findall(output.stdout)
        assert_that(len(match),"There should be atleast 1 NUMA node").is_greater_than(0)
        return len(match)
    
    def get_sysbench_memory_output(self, 
                            nodeId: int,
                            threads: Optional[str] = None,
                            memory_scope : Optional[str] = None,
                            memory_oper : Optional[str] = None,
                            memory_block_size : Optional[str] = None,
                            memory_access_mode : Optional[str] = None,
                            memory_hugetlb: Optional[str] = None,
                            memory_total_size: Optional[str] = None,
                            ) -> ExecutableResult:
        if not self._is_installed("sysbench"):
            posix_os: Posix = cast(Posix, self.node.os)
            posix_os.install_packages("sysbench")

        cmd=f" --membind {nodeId} sysbench"
        if threads:
            cmd += f" --threads={threads}"
        
        cmd += " memory"
        
        if memory_scope:
            cmd += f" --memory-scope={memory_scope}"
        
        if memory_oper:
            cmd += f" --memory-oper={memory_oper}"

        if memory_block_size:
            cmd += f" --memory-block-size={memory_block_size}"

        if memory_access_mode:
            cmd += f" --memory-access-mode={memory_access_mode}"
        
        if memory_hugetlb:
            cmd += f" --memory-hugetlb={memory_hugetlb}"

        if memory_total_size:
            cmd += f" --memory-total-size={memory_total_size}"

        cmd += " run"

        output = self.run(cmd)
        return output
    
    def get_node_speed(self,
                       output: ExecutableResult) -> float:
        match = self.__avg_speed.findall(output.stdout)
        return float(match[0])
    
    def get_node_time(self,
                      output: ExecutableResult) -> float:
        match = self.__total_time.findall(output.stdout)
        return float(match[0])