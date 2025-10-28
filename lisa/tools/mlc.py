import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Set, Type

from lisa.base_tools.wget import Wget
from lisa.executable import Tool
from lisa.operating_system import Redhat, Suse, Ubuntu
from lisa.tools import Dmesg
from lisa.tools.echo import Echo
from lisa.tools.tar import Tar
from lisa.util import LisaException, find_groups_in_lines
from lisa.util.process import ExecutableResult

from .ln import Ln
from .python import Python
class Mlc(Tool):
    
    _mlc_pkg = (
        "https://downloadmirror.intel.com/822971/mlc_v3.11a.tgz"
    )
    # Intel(R) Memory Latency Checker - v3.11
    # ....
    # Measuring idle latencies for random access (in ns)...
    #
    #          Numa node
    #
    #Numa node           0       1       2
    #
    #     0         130.2  231.2   265.7
    #
    #     1         238.2  130.1   368.7
    # ....
    __mlc_latencies = re.compile(r"Measuring idle latencies for random access \(in ns\)\.\.\.\n\n\s+"
                                 r"Numa node\n\n"
                                 r"Numa node(?:\s+\d)+(?:\n\n\s+\d(?:\s+\d+\.\d+)+)+")
    # Intel(R) Memory Latency Checker - v3.11
    # ....
    # Measuring Memory Bandwidths between nodes within system
    #
    #Bandwidths are in MB/sec (1 MB/sec = 1,000,000 Bytes/sec)
    #
    #Using all the threads from each core if Hyper-threading is enabled
    #
    #Using Read-only traffic type
    #
    #              Numa node
    #
    #Numa node           0       1       2
    #
    #     0        79808.6 60065.8 31322.0
    #
    #     1        68081.3 78793.6 27324.0
    # ....
    __mlc_bandwidths = re.compile(r"Measuring Memory Bandwidths between nodes within system\n\n"
                                  r"(?:.*\n)*?"
                                  r"\s+Numa node\n\n"
                                  r"Numa node(?:\s+\d)+(?:\n\n\s+\d(?:\s+\d+\.\d+)+)+")
    
    __node_data = re.compile("(\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)")
    @property
    def command(self) -> str:
        return "mlc"


    @property
    def can_install(self) -> bool:
        return True

    def _install_from_src(self) -> None:
        wget_tool = self.node.tools[Wget]
        tar = self.node.tools[Tar]
        ln = self.node.tools[Ln]
        file_path = wget_tool.get(self._mlc_pkg)
        tar.extract(file=file_path,dest_dir=self.node.working_path.joinpath("mlc"))
        if self.node.is_posix:
            ln.create_link(self.node.working_path.joinpath("mlc/Linux/mlc"),"/usr/bin/mlc")
        else:
            ln.create_link(self.node.working_path.joinpath("mlc/Windows/mlc"),"/usr/bin/mlc")

    def install(self) -> bool:
        self._install_from_src()
        return self._check_exists()
    
    def get_mlc_output(self) -> ExecutableResult:
        echo = self.node.tools[Echo]
        echo.write_to_file("4000","/proc/sys/vm/nr_hugepages",sudo=True)

        return self.run()
    
    def get_latency_data(self):
        output = self.get_mlc_output()
        latency_data = self.__mlc_latencies.findall(output.stdout)

        return latency_data[0]
    
    def get_bandwidth_data(self):
        output = self.get_mlc_output()
        bandwidth_data = self.__mlc_bandwidths.findall(output.stdout)

        return bandwidth_data[0]
    
    def get_node_details(self, node_id, data):
        matches = self.__node_data.findall(data)
        ans = []
        for match in matches:
            row = match[1:]
            ans.append(float(row[node_id]))

        return ans