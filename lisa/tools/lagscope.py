# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Type, cast

from lisa.executable import Tool
from lisa.messages import NetworkLatencyPerformanceMessage, create_message
from lisa.operating_system import Debian, Posix, Redhat, Suse
from lisa.util import (
    LisaException,
    constants,
    find_patterns_groups_in_lines,
    get_datetime_path,
)
from lisa.util.process import ExecutableResult, Process

from .git import Git

if TYPE_CHECKING:
    from lisa.environment import Environment


class Lagscope(Tool):
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

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git]

    @property
    def command(self) -> str:
        return "lagscope"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        self._install_dep_packages()
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path, ref=self.branch)
        code_path = tool_path.joinpath("lagscope")
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

    def run_as_server(self, ip: str = "", daemon: bool = True) -> None:
        # -r: run as a receiver
        # -rip: run as server mode with specified ip address
        # -D: run as a daemon
        cmd = ""
        if daemon:
            cmd += " -D"
        if ip:
            cmd += f" -r{ip}"
        else:
            cmd += " -r"
        self.run(
            cmd,
            force_run=True,
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to launch cmd {self.command}"
            f"{cmd}",
        )

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
        return process.wait_result()

    def get_average(self, result: ExecutableResult) -> Decimal:
        matched_results = self._average_pattern.match(result.stdout)
        assert (
            matched_results
        ), "not found matched average latency statistics from lagscope results."
        return Decimal(matched_results.group("average_latency_us"))

    def create_latency_peformance_messages(
        self, result: ExecutableResult, environment: "Environment", test_case_name: str
    ) -> List[NetworkLatencyPerformanceMessage]:
        matched_results = self._result_pattern.match(result.stdout)
        assert (
            matched_results
        ), "not found matched latency statistics from lagscope results."
        all_matched_results = find_patterns_groups_in_lines(
            result.stdout, [self._interval_frequency_pattern]
        )[0]
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
            message = create_message(
                NetworkLatencyPerformanceMessage,
                self.node,
                environment,
                test_case_name,
                other_fields,
            )
            perf_message_list.append(message)
        return perf_message_list

    def _install_dep_packages(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        if isinstance(self.node.os, Redhat):
            package_list = [
                "make",
                "gcc",
                "libaio",
                "sysstat",
                "bc",
                "wget",
                "cmake",
                "libarchive",
            ]
        elif isinstance(self.node.os, Debian):
            package_list = [
                "make",
                "gcc",
                "libaio1",
                "sysstat",
                "cmake",
            ]
        elif isinstance(self.node.os, Suse):
            package_list = [
                "make",
                "gcc",
                "sysstat",
                "bc",
                "blktrace",
                "dstat",
                "psmisc",
                "cmake",
            ]
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        for package in list(package_list):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)
