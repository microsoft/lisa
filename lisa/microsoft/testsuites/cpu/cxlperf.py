from pathlib import PurePath
from assertpy.assertpy import assert_that
from lisa.base_tools.uname import Uname
from lisa.base_tools.wget import Wget
from lisa.environment import Environment
from lisa import (
    LisaException,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Ubuntu
from lisa.tools.echo import Echo
from lisa.tools.mkdir import Mkdir
from lisa.tools.mlc import Mlc
from lisa.tools.numactl import Numactl
from lisa.tools.tar import Tar
from lisa.util import UnsupportedDistroException
from lisa.util.logger import Logger
from lisa.environment import EnvironmentStatus

@TestSuiteMetadata(
    area="cpu",
    category="functional",
    description="""
    This test suite verifies the performance of cxl node when compared to numa node
    """,
)

class CXLPerformance(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case check the following for a VM with only 1 CXL node.
        1) Checks if CXL node is present in the VM.
        2) Verifies that CXL node time and latency is greater than that of NUMA node.
        3) Verifies that CXL node bandwidth and speed are less than that of NUMA node.
        """,
    )
    def verify_cxl_latency(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        self._install_dependencies(node)
        mlc_pkg = "https://downloadmirror.intel.com/822971/mlc_v3.11a.tgz"

        #Run numactl -H
        #check for available nodes
        #confirm that the last node i.e. CXL node does not contain any cpus

        numactl_tool = node.tools[Numactl]
        cxl_node = numactl_tool.get_cxl_node()
        numa_nodes = numactl_tool.get_numa_nodes()
        #Run sysbench which required parameters for cxl and numa nodes
        #check for execution time and speed of execution to transfer 8gb
        #Sysbench output as follows -->
        #sysbench 1.0.20
        #
        #Running the test with following options:
        #......
        #8192.00MiB transferred (183.53 MiB/sec)
        #......
        #General statistis:
        #   total time:     44.6566s
        #......
        sysbench_cxl_output = numactl_tool.get_sysbench_memory_output(nodeId=cxl_node,
                                                                      threads=1,
                                                                      memory_scope="local",
                                                                      memory_access_mode="rnd",
                                                                      memory_block_size="8g",
                                                                      memory_oper="write")
         
        cxl_speed = numactl_tool.get_node_speed(sysbench_cxl_output)
        cxl_time = numactl_tool.get_node_time(sysbench_cxl_output)

        for nodeNum in range(numa_nodes):
            sysbench_numa_output = numactl_tool.get_sysbench_memory_output(nodeId=nodeNum,threads=1,memory_scope="local",memory_access_mode="rnd",memory_block_size="8g",memory_oper="write")
            numa_speed = numactl_tool.get_node_speed(sysbench_numa_output)
            numa_time = numactl_tool.get_node_time(sysbench_numa_output)
             #Confirm that speed of cxl node is less than numa node and time taken for CXL node is more than that of numa node
            assert_that(cxl_speed).described_as(f"CXL node speed should be greater than the {nodeNum}th Numa Node").is_greater_than(numa_speed)
            assert_that(cxl_time).described_as(f"CXL node time should be more than {nodeNum}th Numa Node").is_greater_than(numa_time)

        #Memory latency checker (mlc)
        #compare the latency and bandwidth from the output
        #mlc output -->
        #Intel(R) Memory Latency Checker - v3.11
        #...
        #...
        #Measuring idle latencies for random access (in ns)...
        #           Numa node
        # Numa node           0       1       2
        #      0         130.2  231.2   265.7
        #      1         238.2  130.1   368.7
        #...
        #Measuring Memory Bandwidths between nodes within system
        #Using Read-only traffic type
        #       Numa node
        # Numa node           0       1       2
        #      0        79808.6 60065.8 31322.0
        #      1        68081.3 78793.6 27324.0
        #...
        mlc = node.tools[Mlc]
        mlc_output = mlc.get_mlc_output()
        latency_data = mlc.get_latency_data(mlc_output)
        cxl_node_latencies = mlc.get_node_details(cxl_node, latency_data)
        for node in range(numa_nodes):
            numa_node_latencies = mlc.get_node_details(node, latency_data)
            for i in range(numa_nodes):
                assert_that(cxl_node_latencies[i]).described_as(f"CXL node {cxl_node} has less latency than numa node {i}").is_greater_than(numa_node_latencies[i])
        
        bandwidth_data = mlc.get_bandwidth_data(mlc_output)
        cxl_node_bandwidths = mlc.get_node_details(cxl_node, bandwidth_data)
        for node in range(numa_nodes):
            numa_node_bandwidths = mlc.get_node_details(node, bandwidth_data)
            for i in range(numa_nodes):
                assert_that(cxl_node_bandwidths[i]).described_as(f"Numa node {i} has less bandwidth than cxl node {cxl_node}").is_less_than(numa_node_bandwidths[i])
        
        return
    
    def _install_dependencies(self, node: Node) -> None:
        ubuntu_required_packages = [
            "numactl",
            "sysbench",
            "hwloc",
            "wget"
        ]
        if isinstance(node.os, Ubuntu) and node.os.information.version >= "2.4.0":
            node.os.install_packages(ubuntu_required_packages)
        else:
            raise UnsupportedDistroException(
                node.os,
                "Ubuntu distros are supported",
            )
        
    def get_cxl_node_and_numa_nodes(self, output: str) -> str:
        lines = output.strip().splitlines()
        for line in lines:
            if "available:" in line:
                total_nodes = int(line.split()[1])
            if "cpus:" in line:
                node, cpus = line.split(' cpus:')
                if not cpus.strip():
                    cxl_node_number=node.split(' ')[1]

        return cxl_node_number,total_nodes-1
    
    def sysbench_output_extract(self, output: str):
        lines = output.strip().splitlines()
        speed=0
        time=0
        for line in lines:
            if "MiB transferred" in line:
                speed = float(line.split('(')[1].split(' ')[0])
            if "total time" in line:
                time = float(line.split(':')[1].split('s')[0].strip())
        return speed, time
    
    def mlc_output_extract(self, output: str,numa_nodes):
        lines = output.strip().splitlines()

        # Extract latency data
        latency_data = []
        found=False
        for i,line in enumerate(lines):
          if "Measuring idle latencies" in line:
            found = True

          if (found and line.startswith("Numa node")):
              for j in range(numa_nodes):
                # print(lines[i+j+1])
                latency_data.append([float(x) for x in lines[i+j+1].split()])
              break

        # Convert latency values to float
        cxl_latencies= [data[numa_nodes+1] for data in latency_data]
        numa_latencies = [data[1:numa_nodes+1] for data in latency_data]

        # Extract bandwidth data
        bandwidth_data=[]
        found=False
        for i,line in enumerate(lines):
          if "Measuring Memory Bandwidths" in line:
            found = True

          if (found and line.startswith("Numa node")):
              for j in range(numa_nodes):
                # print(lines[i+j+1])
                bandwidth_data.append([float(x) for x in lines[i+j+1].split()])
              break

        # Convert latency values to float
        cxl_bandwidth= [data[numa_nodes+1] for data in bandwidth_data]
        numa_bandwidths = [data[1:numa_nodes+1] for data in bandwidth_data]

        return cxl_latencies,cxl_bandwidth,numa_latencies,numa_bandwidths
    
    
    
    def download(self,package,node:Node) -> PurePath:
        if not node.shell.exists(node.working_path.joinpath("mlc")):
            wget_tool = node.tools[Wget]
            # mkdir_tool = node.tools[Mkdir]
            tar = node.tools[Tar]
            
            pkg_path = wget_tool.get(package, str(node.working_path))
            # mkdir_tool.create_directory(str(node.working_path)+"mlc")
            tar.extract(file=pkg_path, dest_dir=str(node.working_path.joinpath("mlc")))

            return node.working_path.joinpath("mlc/Linux")