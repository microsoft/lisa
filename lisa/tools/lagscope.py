# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, cast

from lisa import notifier
from lisa.executable import Tool
from lisa.messages import (
    MetricRelativity,
    NetworkLatencyPerformanceMessage,
    create_perf_message,
    send_unified_perf_message,
)
from lisa.operating_system import CBLMariner, Debian, Posix, Redhat, Suse
from lisa.util import LisaException, constants, find_groups_in_lines, get_datetime_path
from lisa.util.process import ExecutableResult, Process

from .firewall import Firewall
from .gcc import Gcc
from .git import Git
from .lsof import Lsof
from .make import Make
from .mixins import KillableMixin
from .sockperf import Sockperf
from .sysctl import Sysctl

if TYPE_CHECKING:
    from lisa.testsuite import TestResult


class Lagscope(Tool, KillableMixin):
    repo = "https://github.com/Microsoft/lagscope"
    # the latest tag doesn't contain changes for 95th,99th percentile.
    branch = "master"

    # lagscope 1.0.1
    # ---------------------------------------------------------
    # 02:06:15 INFO: New connection: local:25001 [socket:3] --> 10.0.0.5:6001
    # 02:11:12 INFO: TEST COMPLETED.
    # 02:11:12 INFO: Ping statistics for 10.0.0.5:
    # 02:11:12 INFO:    Number of successful Pings: 1000000
    # 02:11:12 INFO:    Minimum = 135.500us, Maximum = 9644.250us, Average = 294.313us
    # 02:11:12 INFO: Dumping all latencies into csv file: Latency-20220106-0817.csv
    #
    # Percentile       Latency(us)
    #      50%         295
    #      75%         345
    #      90%         362
    #      95%         376
    #      99%         404
    #    99.9%         620
    #   99.99%         135
    #  99.999%         2654
    _result_pattern = re.compile(
        r"([\w\W]*?)Minimum = (?P<min_latency_us>.+?)us, "
        r"Maximum = (?P<max_latency_us>.+?)us, Average = (?P<average_latency_us>.+?)us"
        r"([\w\W]*?)95%\s+(?P<latency95_percentile_us>\d+)"
        r"([\w\W]*?)99%\s+(?P<latency99_percentile_us>\d+)",
        re.M,
    )
    # Interval(usec)   Frequency
    #       0          0
    #      30          0
    #      45          0
    #      60          0
    #      75          0
    #      90          0
    #     105          0
    #     120          0
    #     135          1013
    #     150          7111
    #     165          15318
    #     180          35440
    #     195          39818
    #     210          63977
    #     225          51341
    #     240          62950
    #     255          78099
    #     270          88724
    #     285          76162
    #     300          52777
    #     315          76238
    #     330          93312
    #     345          141943
    #     360          62452
    #     375          32662
    #     390          10980
    #     405          3605
    #     420          1786
    #     435          992
    #     450          639
    #     465          457
    #     480          2204
    _interval_frequency_pattern = re.compile(
        r"\s+(?P<interval_us>\d+)\s+(?P<frequency>\d+)$", re.M
    )
    _average_pattern = re.compile(
        r"([\w\W]*?)Average = (?P<average_latency_us>.+?)us", re.M
    )
    _busy_pool_keys = ["net.core.busy_poll", "net.core.busy_read"]
    # 08:19:33 ERR : failed to connect to receiver: 10.0.1.4:6001
    #  on socket: 3. errno = 113
    _client_failure_pattern = re.compile(r"^(?P<error>.*? ERR : .*?)\r?$", re.M)

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make, Gcc]

    @property
    def command(self) -> str:
        return "lagscope"

    @property
    def can_install(self) -> bool:
        return True

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return BSDLagscope

    def set_busy_poll(self) -> None:
        # Busy polling helps reduce latency in the network receive path by
        #  allowing socket layer code to poll the receive queue of a network
        #  device, and disabling network interrupts. This removes delays caused
        #  by the interrupt and the resultant context switch. However, it also
        #  increases CPU utilization. Busy polling also prevents the CPU from
        #  sleeping, which can incur additional power consumption.
        sysctl = self.node.tools[Sysctl]
        for key in self._busy_pool_keys:
            sysctl.write(key, "50")

    def restore_busy_poll(self) -> None:
        sysctl = self.node.tools[Sysctl]
        for key in self._busy_pool_keys:
            sysctl.write(key, self._original_settings[key])

    def run_as_server_async(self, ip: str = "") -> Process:
        # -r: run as a receiver
        # -rip: run as server mode with specified ip address
        cmd = ""
        if ip:
            cmd += f" -r{ip}"
        else:
            cmd += " -r"
        process = self.run_async(cmd, sudo=True, shell=True, force_run=True)
        if not process.is_running():
            raise LisaException("lagscope server failed to start")
        if not self.node.tools[Lsof].is_port_opened_per_process_name(self.command):
            raise LisaException("no port opened for lagscope server")
        return process

    def run_as_client_async(
        self,
        server_ip: str,
        test_interval: int = 0,
        run_time_seconds: int = 10,
        ping_count: int = 0,
        print_histogram: bool = True,
        print_percentile: bool = True,
        histogram_1st_interval_start_value: int = 30,
        length_of_histogram_intervals: int = 15,
        count_of_histogram_intervals: int = 30,
        dump_csv: bool = True,
        daemon: bool = False,
    ) -> Process:
        # -s: run as a sender
        # -i: test interval
        # -n: ping iteration
        # -H: print histogram of per-iteration latency values
        # -P: prints 50th, 75th, 90th, 95th, 99th, 99.9th, 99.99th, 99.999th percentile
        #  of latencies
        # -a: histogram 1st interval start value
        # -l: length of histogram intervals
        # -c: count of histogram intervals
        # -R: dumps raw latencies into csv file
        # -D: run as daemon
        cmd = f"{self.command} -s{server_ip} "
        if run_time_seconds:
            cmd += f" -t{run_time_seconds} "
        if count_of_histogram_intervals:
            cmd += f" -c{count_of_histogram_intervals} "
        if length_of_histogram_intervals:
            cmd += f" -l{length_of_histogram_intervals} "
        if histogram_1st_interval_start_value:
            cmd += f" -a{histogram_1st_interval_start_value} "
        if ping_count:
            cmd += f" -n{ping_count} "
        if test_interval:
            cmd += f" -i{test_interval} "
        if daemon:
            cmd += " -D "
        if print_histogram:
            cmd += " -H "
        if print_percentile:
            cmd += " -P "
        if dump_csv:
            cmd += f" -RLatency-{get_datetime_path()}.csv "
        process = self.node.execute_async(cmd, shell=True)
        return process

    def run_as_client(
        self,
        server_ip: str,
        test_interval: int = 0,
        run_time_seconds: int = 10,
        ping_count: int = 0,
        print_histogram: bool = True,
        print_percentile: bool = True,
        histogram_1st_interval_start_value: int = 30,
        length_of_histogram_intervals: int = 15,
        count_of_histogram_intervals: int = 30,
        dump_csv: bool = True,
        daemon: bool = False,
    ) -> ExecutableResult:
        process = self.run_as_client_async(
            server_ip,
            test_interval,
            run_time_seconds,
            ping_count,
            print_histogram,
            print_percentile,
            histogram_1st_interval_start_value,
            length_of_histogram_intervals,
            count_of_histogram_intervals,
            dump_csv,
            daemon,
        )

        result = process.wait_result()
        errors = find_groups_in_lines(result.stdout, self._client_failure_pattern)
        if errors:
            raise LisaException(
                f"lagscope client error: {[x['error'] for x in errors]}"
            )

        return result

    def get_average(self, result: ExecutableResult) -> Decimal:
        matched_results = self._average_pattern.match(result.stdout)
        if matched_results:
            return Decimal(matched_results.group("average_latency_us"))
        else:
            self._log.debug(f"no average latency found in {result.stdout}")
            return Decimal(-1.0)

    def _send_latency_unified_perf_messages(
        self,
        other_fields: Dict[str, Any],
        test_case_name: str,
        test_result: "TestResult",
    ) -> None:
        """Send unified performance messages for network latency metrics."""
        tool = constants.NETWORK_PERFORMANCE_TOOL_LAGSCOPE

        min_latency_us = other_fields["min_latency_us"]
        max_latency_us = other_fields["max_latency_us"]
        average_latency_us = other_fields["average_latency_us"]
        latency95_percentile_us = other_fields.get(
            "latency95_percentile_us", Decimal(0)
        )
        latency99_percentile_us = other_fields["latency99_percentile_us"]
        interval_us = other_fields["interval_us"]
        frequency = other_fields["frequency"]

        metrics = [
            {
                "name": (
                    f"min_latency_interval_{int(interval_us)}_freq_{int(frequency)}"
                ),
                "value": float(min_latency_us),
                "unit": "microseconds",
                "description": "Minimum latency",
                "relativity": MetricRelativity.LowerIsBetter,
            },
            {
                "name": (
                    f"max_latency_interval_{int(interval_us)}_freq_{int(frequency)}"
                ),
                "value": float(max_latency_us),
                "unit": "microseconds",
                "description": "Maximum latency",
                "relativity": MetricRelativity.LowerIsBetter,
            },
            {
                "name": (
                    f"average_latency_interval_{int(interval_us)}_freq_{int(frequency)}"
                ),
                "value": float(average_latency_us),
                "unit": "microseconds",
                "description": "Average latency",
                "relativity": MetricRelativity.LowerIsBetter,
            },
            {
                "name": (
                    "latency_95th_percentile_interval_"
                    f"{int(interval_us)}_freq_{int(frequency)}"
                ),
                "value": float(latency95_percentile_us),
                "unit": "microseconds",
                "description": "95th percentile latency",
                "relativity": MetricRelativity.LowerIsBetter,
            },
            {
                "name": (
                    "latency_99th_percentile_interval_"
                    f"{int(interval_us)}_freq_{int(frequency)}"
                ),
                "value": float(latency99_percentile_us),
                "unit": "microseconds",
                "description": "99th percentile latency",
                "relativity": MetricRelativity.LowerIsBetter,
            },
        ]

        for metric in metrics:
            metric_name: str = metric["name"]  # type: ignore
            metric_value: float = metric["value"]  # type: ignore
            metric_unit: str = metric["unit"]  # type: ignore
            metric_description: str = metric["description"]  # type: ignore
            metric_relativity: MetricRelativity = metric["relativity"]  # type: ignore

            send_unified_perf_message(
                node=self.node,
                test_result=test_result,
                test_case_name=test_case_name,
                tool=tool,
                metric_name=metric_name,
                metric_value=metric_value,
                metric_unit=metric_unit,
                metric_description=metric_description,
                metric_relativity=metric_relativity,
            )

    def create_latency_performance_messages(
        self,
        result: ExecutableResult,
        test_case_name: str,
        test_result: "TestResult",
    ) -> List[NetworkLatencyPerformanceMessage]:
        matched_results = self._result_pattern.match(result.stdout)
        assert (
            matched_results
        ), "not found matched latency statistics from lagscope results."
        all_matched_results = find_groups_in_lines(
            result.stdout, self._interval_frequency_pattern
        )
        perf_message_list: List[NetworkLatencyPerformanceMessage] = []
        for matched_result in all_matched_results:
            other_fields: Dict[str, Any] = {}
            other_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_LAGSCOPE
            other_fields["min_latency_us"] = Decimal(
                matched_results.group("min_latency_us")
            )
            other_fields["max_latency_us"] = Decimal(
                matched_results.group("max_latency_us")
            )
            other_fields["average_latency_us"] = Decimal(
                matched_results.group("average_latency_us")
            )
            other_fields["latency95_percentile_us"] = Decimal(
                matched_results.group("latency95_percentile_us")
            )
            other_fields["latency99_percentile_us"] = Decimal(
                matched_results.group("latency99_percentile_us")
            )
            other_fields["frequency"] = int(matched_result["frequency"])
            other_fields["interval_us"] = int(matched_result["interval_us"])

            # Send unified performance messages
            self._send_latency_unified_perf_messages(
                other_fields=other_fields,
                test_case_name=test_case_name,
                test_result=test_result,
            )

            message = create_perf_message(
                NetworkLatencyPerformanceMessage,
                self.node,
                test_result,
                test_case_name,
                other_fields,
            )
            perf_message_list.append(message)
            notifier.notify(message)
        return perf_message_list

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        firewall = self.node.tools[Firewall]
        firewall.stop()

        # save the original value for recovering
        self._original_settings: Dict[str, str] = {}
        sysctl = self.node.tools[Sysctl]
        for key in self._busy_pool_keys:
            self._original_settings[key] = sysctl.get(key)

    def _install(self) -> bool:
        self._install_dep_packages()
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path, ref=self.branch)
        code_path = tool_path.joinpath("lagscope")

        src_path = code_path.joinpath("src")

        # Get the installed CMake version dynamically
        cmake_version_result = self.node.execute(
            "cmake --version | head -n1 | awk '{print $3}' | cut -d. -f1,2",
            shell=True,
        )

        cmake_version = "3.5"  # Safe default fallback
        if cmake_version_result.exit_code == 0 and cmake_version_result.stdout:
            # Clean the output: remove all whitespace and control characters
            raw_version = cmake_version_result.stdout
            # Extract only the first valid version pattern (digits.digits)
            import re

            version_match = re.search(r"^(\d+\.\d+)", raw_version.strip())
            if version_match:
                cmake_version = version_match.group(1)
                self._log.debug(f"Detected CMake version: {cmake_version}")
            else:
                self._log.debug(
                    f"Could not parse CMake version from '{raw_version}', "
                    f"using fallback: {cmake_version}"
                )
        else:
            self._log.debug(
                f"Could not detect CMake version, using fallback: {cmake_version}"
            )

        # Update CMakeLists.txt with the detected version
        self.node.execute(
            f"sed -i 's/cmake_minimum_required(VERSION [0-9.]\\+)/"
            f"cmake_minimum_required(VERSION {cmake_version})/' "
            f"{src_path}/CMakeLists.txt",
            cwd=code_path,
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to update src/CMakeLists.txt",
        )

        self.node.execute(
            "./do-cmake.sh build",
            cwd=code_path,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run do-cmake.sh build",
        )
        self.node.execute(
            "./do-cmake.sh install",
            cwd=code_path,
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run do-cmake.sh install",
        )
        self.node.execute(
            "ln -sf /usr/local/bin/lagscope /usr/bin/lagscope",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to create symlink to lagscope",
        )
        return self._check_exists()

    def _install_dep_packages(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        if isinstance(self.node.os, Redhat):
            package_list = [
                "libaio",
                "sysstat",
                "bc",
                "wget",
                "cmake",
                "libarchive",
            ]
        elif isinstance(self.node.os, Debian):
            package_list = [
                "libaio1",
                "sysstat",
                "cmake",
            ]
        elif isinstance(self.node.os, Suse):
            package_list = [
                "sysstat",
                "bc",
                "blktrace",
                "dstat",
                "psmisc",
                "cmake",
            ]
        elif isinstance(self.node.os, CBLMariner):
            package_list = [
                "kernel-headers",
                "binutils",
                "glibc-devel",
                "zlib-devel",
                "cmake",
            ]
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        for package in list(package_list):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)


class BSDLagscope(Lagscope):
    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        firewall = self.node.tools[Firewall]
        firewall.stop()

    def get_average(self, result: ExecutableResult) -> Decimal:
        return self.node.tools[Sockperf].get_average_latency(result.stdout)

    def set_busy_poll(self) -> None:
        # This is not supported on FreeBSD.
        return

    def restore_busy_poll(self) -> None:
        # This is not supported on FreeBSD.
        return

    def run_as_server_async(self, ip: str = "") -> Process:
        return self.node.tools[Sockperf].start_server_async("tcp")

    def run_as_client_async(
        self,
        server_ip: str,
        test_interval: int = 0,
        run_time_seconds: int = 10,
        ping_count: int = 0,
        print_histogram: bool = True,
        print_percentile: bool = True,
        histogram_1st_interval_start_value: int = 30,
        length_of_histogram_intervals: int = 15,
        count_of_histogram_intervals: int = 30,
        dump_csv: bool = True,
        daemon: bool = False,
    ) -> Process:
        return self.node.tools[Sockperf].run_client_async("tcp", server_ip)

    def run_as_client(
        self,
        server_ip: str,
        test_interval: int = 0,
        run_time_seconds: int = 10,
        ping_count: int = 0,
        print_histogram: bool = True,
        print_percentile: bool = True,
        histogram_1st_interval_start_value: int = 30,
        length_of_histogram_intervals: int = 15,
        count_of_histogram_intervals: int = 30,
        dump_csv: bool = True,
        daemon: bool = False,
    ) -> ExecutableResult:
        process = self.run_as_client_async(
            server_ip,
            test_interval,
            run_time_seconds,
            ping_count,
            print_histogram,
            print_percentile,
            histogram_1st_interval_start_value,
            length_of_histogram_intervals,
            count_of_histogram_intervals,
            dump_csv,
            daemon,
        )
        result = process.wait_result()
        return result

    def create_latency_performance_messages(
        self, result: ExecutableResult, test_case_name: str, test_result: "TestResult"
    ) -> List[NetworkLatencyPerformanceMessage]:
        stats = self.node.tools[Sockperf].get_statistics(result.stdout)

        perf_message_list: List[NetworkLatencyPerformanceMessage] = []
        other_fields: Dict[str, Any] = {}
        other_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_LAGSCOPE
        other_fields["min_latency_us"] = stats["min_latency_us"]
        other_fields["max_latency_us"] = stats["max_latency_us"]
        other_fields["average_latency_us"] = stats["average_latency_us"]
        other_fields["latency99_percentile_us"] = stats["latency99_percentile_us"]
        other_fields["frequency"] = (
            stats["total_observations"] / stats["run_time_seconds"]
        )
        other_fields["interval_us"] = stats["run_time_seconds"] * 1000000

        # Send unified performance messages
        # Note: BSDLagscope uses sockperf which doesn't provide 95th percentile
        self._send_latency_unified_perf_messages(
            other_fields=other_fields,
            test_case_name=test_case_name,
            test_result=test_result,
        )

        message = create_perf_message(
            NetworkLatencyPerformanceMessage,
            self.node,
            test_result,
            test_case_name,
            other_fields,
        )
        perf_message_list.append(message)
        notifier.notify(message)

        return perf_message_list
