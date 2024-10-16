# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from lisa.executable import Tool
from lisa.messages import (
    NetworkTCPPerformanceMessage,
    NetworkUDPPerformanceMessage,
    TransportProtocol,
    create_perf_message,
)
from lisa.operating_system import BSD, CBLMariner
from lisa.tools import Firewall, Gcc, Git, Lscpu, Make, Sed
from lisa.tools.taskset import TaskSet
from lisa.util import LisaException, constants
from lisa.util.process import ExecutableResult, Process

from .sysctl import Sysctl

if TYPE_CHECKING:
    from lisa.testsuite import TestResult

NTTTCP_TCP_CONCURRENCY = [
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    256,
    512,
    1024,
    2048,
    4096,
    6144,
    8192,
    10240,
    20480,
]
# Running NTTTCP in BSD results in error:
# ERR : error happened when select()
NTTTCP_TCP_CONCURRENCY_BSD = [
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    256,
    512,
]
NTTTCP_UDP_CONCURRENCY = [
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    256,
    512,
    1024,
]


class NtttcpResult:
    role: str = "server"
    connections_created_time: Decimal = Decimal(0)
    throughput_in_gbps: Decimal = Decimal(0)
    retrans_segs: Decimal = Decimal(0)
    tx_packets: Decimal = Decimal(0)
    rx_packets: Decimal = Decimal(0)
    pkts_interrupt: Decimal = Decimal(0)
    cycles_per_byte: Decimal = Decimal(0)


class Ntttcp(Tool):
    repo = "https://github.com/microsoft/ntttcp-for-linux"
    throughput_pattern = re.compile(r" 	 throughput	:(.+)")
    # NTTTCP output sample
    # NTTTCP for Linux 1.4.0
    # ---------------------------------------------------------
    # Test cycle time negotiated is: 122 seconds
    # 1 threads created
    # 1 connections created in 1156 microseconds
    # Network activity progressing...
    # Test warmup completed.
    # Test run completed.
    # Test cooldown is in progress...
    # Test cycle finished.
    # receiver exited from current test
    # 1 connections tested
    # #####  Totals:  #####
    # test duration	:120.36 seconds
    # total bytes	:135945781248
    #     throughput	:9.04Gbps
    #     retrans segs	:679
    # total packets:
    #     tx_packets	:2895248
    #     rx_packets	:3240673
    # interrupts:
    #     total		:2769054
    #     pkts/interrupt	:2.22
    # cpu cores	:72
    #     cpu speed	:2593.905MHz
    #     user		:0.03%
    #     system		:0.41%
    #     idle		:99.56%
    #     iowait		:0.00%
    #     softirq	:0.00%
    #     cycles/byte	:0.73
    # cpu busy (all)	:26.81%
    output_pattern = re.compile(
        r"(([\w\W]*?)connections created in "
        r"(?P<connections_created_time>.+) microseconds)?([\w\W]*?)Totals:([\w\W]*?)"
        r"throughput.*:(?P<throughput>.+)(?P<unit>Mbps|Gbps)(([\w\W]*?)"
        r"retrans segs.*:(?P<retrans_segs>.+))?"
        r"([\w\W]*?)tx_packets.*:(?P<tx_packets>.+)"
        r"([\w\W]*?)rx_packets.*:(?P<rx_packets>.+)"
        r"(([\w\W]*?)pkts/interrupt.*:(?P<pkts_interrupt>.+))?"
        r"([\w\W]*?)cycles/byte.*:(?P<cycles_per_byte>.+)",
        re.MULTILINE,
    )
    sys_list_tcp = [
        {"kernel.pid_max": "122880"},
        {"vm.max_map_count": "655300"},
        {"net.ipv4.ip_local_port_range": "1024 65535"},
        # This parameter configures the minimum, default,
        # and maximum sizes for TCP receive buffers to
        # optimize network performance based on available bandwidth and latency.
        {"net.ipv4.tcp_rmem": "4096 87380 16777216"},
    ]
    sys_list_udp = [
        {"net.core.rmem_max": "67108864"},
        {"net.core.rmem_default": "67108864"},
        {"net.core.wmem_default": "67108864"},
        {"net.core.wmem_max": "67108864"},
    ]
    tool_path_folder = "ntttcp-for-linux/src"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make, Gcc]

    @property
    def command(self) -> str:
        return "ntttcp"

    @property
    def can_install(self) -> bool:
        return True

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return BSDNtttcp

    def setup_system(self, udp_mode: bool = False, set_task_max: bool = True) -> None:
        sysctl = self.node.tools[Sysctl]
        sys_list = self.sys_list_tcp
        if set_task_max:
            self._set_tasks_max()
        if udp_mode:
            sys_list = self.sys_list_udp
        for sys in sys_list:
            for variable, value in sys.items():
                sysctl.write(variable, value)
        firewall = self.node.tools[Firewall]
        firewall.stop()

    def restore_system(self, udp_mode: bool = False) -> None:
        original_settings = self._original_settings_tcp
        if udp_mode:
            original_settings = self._original_settings_udp
        self.node.close()
        sysctl = self.node.tools[Sysctl]
        for variable_list in original_settings:
            # restore back to the original value after testing
            for variable, value in variable_list.items():
                sysctl.write(variable, value)

    def help(self) -> ExecutableResult:
        return self.run("-h")

    def get_throughput(self, stdout: str) -> str:
        throughput = self.throughput_pattern.findall(stdout)
        if throughput:
            result: str = throughput[0]
        else:
            result = "cannot find throughput"
        return result

    def run_as_server_async(
        self,
        nic_name: str,
        run_time_seconds: int = 10,
        ports_count: int = 64,
        buffer_size: int = 64,
        cool_down_time_seconds: int = 1,
        warm_up_time_seconds: int = 1,
        use_epoll: bool = True,
        server_ip: str = "",
        dev_differentiator: str = "Hypervisor callback interrupts",
        run_as_daemon: bool = False,
        udp_mode: bool = False,
    ) -> Process:
        cmd = ""
        if server_ip:
            cmd += f" -r{server_ip} "
        cmd += (
            f" -P {ports_count} -t {run_time_seconds} -W {warm_up_time_seconds} "
            f"-C {cool_down_time_seconds} -b {buffer_size}k "
            f"--show-nic-packets {nic_name} "
        )
        if udp_mode:
            cmd += " -u "
        if use_epoll:
            cmd += " -e "
        if dev_differentiator:
            cmd += f" --show-dev-interrupts {dev_differentiator} "
        if run_as_daemon:
            cmd += " -D "

        process = self.node.execute_async(
            f"ulimit -n 204800 && {self.pre_command}{self.command} {cmd}",
            shell=True,
            sudo=True,
        )
        # NTTTCP for Linux 1.4.0
        # ---------------------------------------------------------
        # 01:16:35 INFO: no role specified. use receiver role
        # 01:16:35 INFO: 65 threads created
        # above output means ntttcp server is ready
        process.wait_output("threads created")
        return process

    def run_as_server(
        self,
        nic_name: str,
        run_time_seconds: int = 10,
        ports_count: int = 64,
        buffer_size: int = 64,
        cool_down_time_seconds: int = 1,
        warm_up_time_seconds: int = 1,
        use_epoll: bool = True,
        server_ip: str = "",
        dev_differentiator: str = "Hypervisor callback interrupts",
        run_as_daemon: bool = False,
        udp_mode: bool = False,
    ) -> ExecutableResult:
        # -rserver_ip: run as a receiver with specified server ip address
        # -P: Number of ports listening on receiver side [default: 16] [max: 512]
        # -t: Time of test duration in seconds [default: 60]
        # -e: [receiver only] use epoll() instead of select()
        # -u: UDP mode     [default: TCP]
        # -W: Warm-up time in seconds          [default: 0]
        # -C: Cool-down time in seconds        [default: 0]
        # -b: <buffer size in n[KMG] Bytes>    [default: 65536 (receiver); 131072
        # (sender)]
        # --show-nic-packets <network interface name>: Show number of packets
        # transferred (tx and rx) through this network interface
        # --show-dev-interrupts <device differentiator>: Show number of interrupts for
        # the devices specified by the differentiator
        # Examples for differentiator: Hyper-V PCIe MSI, mlx4, Hypervisor callback
        # interrupts
        process = self.run_as_server_async(
            nic_name,
            run_time_seconds,
            ports_count,
            buffer_size,
            cool_down_time_seconds,
            warm_up_time_seconds,
            use_epoll,
            server_ip,
            dev_differentiator,
            run_as_daemon,
            udp_mode,
        )

        return self.wait_server_result(process)

    def wait_server_result(self, process: Process) -> ExecutableResult:
        return process.wait_result(
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to launch ntttcp server",
        )

    def run_as_client(
        self,
        nic_name: str,
        server_ip: str,
        threads_count: int,
        run_time_seconds: int = 10,
        ports_count: int = 64,
        buffer_size: int = 64,
        cool_down_time_seconds: int = 1,
        warm_up_time_seconds: int = 1,
        dev_differentiator: str = "Hypervisor callback interrupts",
        run_as_daemon: bool = False,
        udp_mode: bool = False,
    ) -> ExecutableResult:
        # -sserver_ip: run as a sender with server ip address
        # -P: Number of ports listening on receiver side [default: 16] [max: 512]
        # -n: [sender only] number of threads per each receiver port     [default: 4]
        # [max: 25600]
        # -t: Time of test duration in seconds [default: 60]
        # -e: [receiver only] use epoll() instead of select()
        # -u: UDP mode     [default: TCP]
        # -W: Warm-up time in seconds          [default: 0]
        # -C: Cool-down time in seconds        [default: 0]
        # -b: <buffer size in n[KMG] Bytes>    [default: 65536 (receiver); 131072
        # (sender)]
        # --show-nic-packets <network interface name>: Show number of packets
        # transferred (tx and rx) through this network interface
        # --show-dev-interrupts <device differentiator>: Show number of interrupts for
        # the devices specified by the differentiator
        # Examples for differentiator: Hyper-V PCIe MSI, mlx4, Hypervisor callback
        # interrupts
        cmd = (
            f" -s{server_ip} -P {ports_count} -n {threads_count} -t {run_time_seconds} "
            f"-W {warm_up_time_seconds} -C {cool_down_time_seconds} -b {buffer_size}k "
            f"--show-nic-packets {nic_name} "
        )
        if udp_mode:
            cmd += " -u "
        if dev_differentiator:
            cmd += f" --show-dev-interrupts {dev_differentiator} "
        if run_as_daemon:
            cmd += " -D "
        result = self.node.execute(
            f"ulimit -n 204800 && {self.pre_command}{self.command} {cmd}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to run {self.command} {cmd}",
        )
        return result

    def create_ntttcp_result(
        self, result: ExecutableResult, role: str = "server"
    ) -> NtttcpResult:
        matched_results = self.output_pattern.match(result.stdout)
        assert matched_results, "not found matched ntttcp results."
        ntttcp_result = NtttcpResult()
        ntttcp_result.role = role
        if "Mbps" == matched_results.group("unit"):
            ntttcp_result.throughput_in_gbps = Decimal(
                Decimal(matched_results.group("throughput")) / 1000
            )
        else:
            ntttcp_result.throughput_in_gbps = Decimal(
                matched_results.group("throughput")
            )
        if matched_results.group("connections_created_time"):
            ntttcp_result.connections_created_time = Decimal(
                matched_results.group("connections_created_time")
            )
        if matched_results.group("pkts_interrupt"):
            ntttcp_result.pkts_interrupt = Decimal(
                matched_results.group("pkts_interrupt")
            )
        if matched_results.group("retrans_segs"):
            ntttcp_result.retrans_segs = Decimal(matched_results.group("retrans_segs"))
        if matched_results.group("rx_packets"):
            ntttcp_result.rx_packets = Decimal(matched_results.group("rx_packets"))
        if matched_results.group("tx_packets"):
            ntttcp_result.tx_packets = Decimal(matched_results.group("tx_packets"))
        ntttcp_result.cycles_per_byte = Decimal(
            matched_results.group("cycles_per_byte")
        )
        return ntttcp_result

    def create_ntttcp_tcp_performance_message(
        self,
        server_result: NtttcpResult,
        client_result: NtttcpResult,
        latency: Decimal,
        connections_num: str,
        buffer_size: int,
        test_case_name: str,
        test_result: "TestResult",
    ) -> NetworkTCPPerformanceMessage:
        other_fields: Dict[str, Any] = {}
        other_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_NTTTCP
        other_fields["buffer_size"] = Decimal(buffer_size)
        other_fields["connections_created_time"] = int(
            client_result.connections_created_time
        )
        other_fields["connections_num"] = int(connections_num)
        other_fields["latency_us"] = latency
        other_fields["retrans_segments"] = int(client_result.retrans_segs)
        other_fields["throughput_in_gbps"] = client_result.throughput_in_gbps
        other_fields["rx_packets"] = server_result.rx_packets
        other_fields["tx_packets"] = client_result.tx_packets
        other_fields["pkts_interrupts"] = client_result.pkts_interrupt
        other_fields["sender_cycles_per_byte"] = client_result.cycles_per_byte
        other_fields["receiver_cycles_rer_byte"] = server_result.cycles_per_byte
        return create_perf_message(
            NetworkTCPPerformanceMessage,
            self.node,
            test_result,
            test_case_name,
            other_fields,
        )

    def create_ntttcp_udp_performance_message(
        self,
        server_result: NtttcpResult,
        client_result: NtttcpResult,
        connections_num: str,
        buffer_size: int,
        test_case_name: str,
        test_result: "TestResult",
    ) -> NetworkUDPPerformanceMessage:
        other_fields: Dict[str, Any] = {}
        other_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_NTTTCP
        other_fields["protocol_type"] = TransportProtocol.Udp
        other_fields["send_buffer_size"] = Decimal(buffer_size)
        other_fields["connections_created_time"] = int(
            client_result.connections_created_time
        )
        other_fields["connections_num"] = int(connections_num)
        other_fields["tx_throughput_in_gbps"] = client_result.throughput_in_gbps
        other_fields["rx_throughput_in_gbps"] = server_result.throughput_in_gbps
        other_fields["receiver_cycles_rer_byte"] = server_result.cycles_per_byte
        other_fields["data_loss"] = (
            100
            * (client_result.throughput_in_gbps - server_result.throughput_in_gbps)
            / client_result.throughput_in_gbps
        )
        return create_perf_message(
            NetworkUDPPerformanceMessage,
            self.node,
            test_result,
            test_case_name,
            other_fields,
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        firewall = self.node.tools[Firewall]
        firewall.stop()

        lscpu = self.node.tools[Lscpu]
        numa_node_count = 1
        try:
            numa_node_count = lscpu.get_numa_node_count()
        except Exception:
            self._log.debug(
                "failed to get numa node count, ",
                "continuing with default numa_node_count = 1",
            )
        self.pre_command: str = ""
        if numa_node_count > 1 and not isinstance(self.node.os, BSD):
            taskset = self.node.tools[TaskSet]
            start_cpu_index, end_cpu_index = lscpu.get_cpu_range_in_numa_node()
            self.pre_command = (
                f"{taskset.command} -c {start_cpu_index}-{end_cpu_index} "
            )
        self._log.debug(f"Numa Node Count: {numa_node_count}")
        self._log.debug(f"ntttcp command: {self.pre_command}{self.command}")

        # save the original value for recovering
        self._original_settings_tcp: List[Dict[str, str]] = []
        self._original_settings_udp: List[Dict[str, str]] = []
        sysctl = self.node.tools[Sysctl]
        for tcp_sys in self.sys_list_tcp:
            for variable, _ in tcp_sys.items():
                self._original_settings_tcp.append({variable: sysctl.get(variable)})
        for udp_sys in self.sys_list_udp:
            for variable, _ in udp_sys.items():
                self._original_settings_udp.append({variable: sysctl.get(variable)})

    def _install(self) -> bool:
        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages(
                [
                    "kernel-headers",
                    "binutils",
                    "glibc-devel",
                    "zlib-devel",
                ]
            )
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        make = self.node.tools[Make]
        code_path = tool_path.joinpath(self.tool_path_folder)
        make.make_install(cwd=code_path)
        if not isinstance(self.node.os, BSD):
            self.node.execute(
                "ln -s /usr/local/bin/ntttcp /usr/bin/ntttcp", sudo=True, cwd=code_path
            ).assert_exit_code()
        return self._check_exists()

    def _set_tasks_max(self) -> None:
        need_reboot = False
        if self.node.shell.exists(
            self.node.get_pure_path(
                "/usr/lib/systemd/system/user-.slice.d/10-defaults.conf"
            )
        ):
            self.node.tools[Sed].substitute(
                regexp="TasksMax.*",
                replacement="TasksMax=122880",
                file="/usr/lib/systemd/system/user-.slice.d/10-defaults.conf",
                sudo=True,
            )
            need_reboot = True
        elif self.node.shell.exists(
            self.node.get_pure_path("/etc/systemd/logind.conf")
        ):
            self.node.tools[Sed].append(
                "UserTasksMax=122880", "/etc/systemd/logind.conf", sudo=True
            )
            need_reboot = True
        else:
            self._log.debug(
                "no config file exist for systemd, either there is no systemd"
                " service or the config file location is incorrect."
            )
        if need_reboot:
            self._log.debug("reboot vm to make sure TasksMax change take effect")
            self.node.reboot()


class BSDNtttcp(Ntttcp):
    repo = "https://github.com/dcui/ntttcp-for-freebsd.git"
    tool_path_folder = "ntttcp-for-freebsd/src"
    # sample output:
    # 15:19:57 INFO: Network activity progressing...
    # 15:20:07 INFO:  Thread  Time(s) Throughput
    # 15:20:07 INFO:  ======  ======= ==========
    # 15:20:07 INFO:  0        10.07   28.91Gbps
    # 15:20:07 INFO: #####  Totals:  #####
    # 15:20:07 INFO: test duration    :10.07 seconds
    # 15:20:07 INFO: total bytes      :36380606464
    # 15:20:07 INFO:   throughput     :28.91Gbps
    # 15:20:07 INFO: total cpu time   :73.64%
    # 15:20:07 INFO:   user time      :36.69%
    # 15:20:07 INFO:   system time    :37.05%
    # 15:20:07 INFO:   cpu cycles     :28123249363
    # 15:20:07 INFO: cycles/byte      :0.77
    output_pattern = re.compile(
        r"([\w\W]*?)Totals:([\w\W]*?)throughput.*:(?P<throughput>.+)(?P<unit>Mbps|Gbps)"
        r"([\w\W]*?)cycles/byte.*:(?P<cycles_per_byte>.+)\r",
        re.MULTILINE,
    )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        firewall = self.node.tools[Firewall]
        firewall.stop()

    def setup_system(self, udp_mode: bool = False, set_task_max: bool = True) -> None:
        # No additional setup is needed for FreeBSD
        return

    def restore_system(self, udp_mode: bool = False) -> None:
        # No additional restore is needed for FreeBSD
        return

    def run_as_server_async(
        self,
        nic_name: str,
        run_time_seconds: int = 10,
        ports_count: int = 64,
        buffer_size: int = 64,
        cool_down_time_seconds: int = 1,
        warm_up_time_seconds: int = 1,
        use_epoll: bool = True,
        server_ip: str = "",
        dev_differentiator: str = "Hypervisor callback interrupts",
        run_as_daemon: bool = False,
        udp_mode: bool = False,
    ) -> Process:
        assert server_ip, "server ip is required for ntttcp server"
        self._log.debug(
            "Paramers nic_name, cool_down_time_seconds, warm_up_time_seconds, "
            "use_epoll and dev_differentiator are not supported in FreeBSD"
        )

        # Setup command
        cmd = (
            f" -r{server_ip} -P {ports_count} -t {run_time_seconds} -b {buffer_size}k "
        )
        if run_as_daemon:
            cmd += " -D "
        if udp_mode:
            raise LisaException("UDP mode is not supported in FreeBSD")

        # Start the server and wait for the threads to be created
        process = self.node.execute_async(
            f"ulimit -n 204800 && {self.pre_command}{self.command} {cmd}",
            shell=True,
            sudo=True,
        )
        time.sleep(5)

        return process

    def run_as_client(
        self,
        nic_name: str,
        server_ip: str,
        threads_count: int,
        run_time_seconds: int = 10,
        ports_count: int = 64,
        buffer_size: int = 64,
        cool_down_time_seconds: int = 1,
        warm_up_time_seconds: int = 1,
        dev_differentiator: str = "Hypervisor callback interrupts",
        run_as_daemon: bool = False,
        udp_mode: bool = False,
    ) -> ExecutableResult:
        self._log.debug(
            "Paramers nic_name, cool_down_time_seconds, warm_up_time_seconds, "
            "use_epoll and dev_differentiator are not supported in FreeBSD"
        )
        cmd = (
            f" -s{server_ip} -P {ports_count} -n {threads_count}"
            f" -t {run_time_seconds}  -b {buffer_size}k "
        )
        if udp_mode:
            raise LisaException("UDP mode is not supported in FreeBSD")
        if run_as_daemon:
            cmd += " -D "
        result = self.node.execute(
            f"ulimit -n 204800 && {self.pre_command}{self.command} {cmd}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to run {self.command} {cmd}",
        )
        return result

    def create_ntttcp_result(
        self, result: ExecutableResult, role: str = "server"
    ) -> NtttcpResult:
        matched_results = self.output_pattern.match(result.stdout)
        assert matched_results, "not found matched ntttcp results."
        ntttcp_result = NtttcpResult()
        ntttcp_result.role = role
        if "Mbps" == matched_results.group("unit"):
            ntttcp_result.throughput_in_gbps = Decimal(
                Decimal(matched_results.group("throughput")) / 1000
            )
        else:
            ntttcp_result.throughput_in_gbps = Decimal(
                matched_results.group("throughput")
            )
        ntttcp_result.cycles_per_byte = Decimal(
            matched_results.group("cycles_per_byte")
        )
        return ntttcp_result
