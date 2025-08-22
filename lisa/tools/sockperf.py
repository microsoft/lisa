# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import pathlib
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Type, Union, cast

from assertpy import assert_that

from lisa import notifier
from lisa.executable import Tool
from lisa.messages import NetworkLatencyPerformanceMessage, create_perf_message
from lisa.operating_system import BSD, CBLMariner, Posix, Ubuntu
from lisa.util import constants
from lisa.util.process import Process

from .firewall import Firewall
from .gcc import Gcc
from .git import Git
from .make import Make

if TYPE_CHECKING:
    from lisa.testsuite import TestResult

SOCKPERF_TCP = "tcp"
SOCKPERF_UDP = "udp"


class Sockperf(Tool):
    @property
    def command(self) -> str:
        return "sockperf"

    @property
    def can_install(self) -> bool:
        # FIXME: skip support for Ubuntu 16.04
        return self.node.is_posix and not (
            isinstance(self.node.os, Ubuntu)
            and (self.node.os.information.version < "18.4.0")
        )

    _sockperf_repo = "https://github.com/Mellanox/sockperf.git"

    sockperf_result_regex = re.compile(
        r"sockperf: ---> <MAX> observation"
        r" =\s+(?P<max_latency_us>[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> percentile 99\.999 "
        r"=\s+(?P<latency99_999_percentile_us>.[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> percentile 99\.990 "
        r"=\s+(?P<latency99_990_percentile_us>.[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> percentile 99\.900 "
        r"=\s+(?P<latency99_900_percentile_us>.[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> percentile 99\.000 "
        r"=\s+(?P<latency99_percentile_us>[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> percentile 90\.000 "
        r"=\s+(?P<latency_us_90>[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> percentile 75\.000 "
        r"=\s+(?P<latency_us_75>[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> percentile 50\.000 "
        r"=\s+(?P<latency_us_50>[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> percentile 25\.000 "
        r"=\s+(?P<latency_us_25>[0-9]+\.[0-9]+)\s+"
        r"sockperf: ---> <MIN> observation "
        r"=\s+(?P<min_latency_us>[0-9]+\.[0-9]+)"
    )

    # Summary: Round trip is 297.328 usec
    sockperf_average_latency = re.compile(
        r"Summary: Round trip is (?P<avg_latency_us>[0-9]+\.[0-9]+) usec"
    )  # noqa: E501

    # Total 1283 observations;
    sockperf_total_observations = re.compile(
        r"Total (?P<total_observations>[0-9]+) observations"
    )  # noqa: E501

    # [Valid Duration] RunTime=0.546 sec; SentMessages=1283; ReceivedMessages=1283
    sockperf_run_time = re.compile(r"RunTime=(?P<run_time>[0-9]+\.[0-9]+) sec")

    def _get_protocol_flag(self, mode: str) -> str:
        assert_that(mode).described_as(
            f"Test bug: unrecogonized option {mode} passed to sockperf."
        ).is_in(SOCKPERF_UDP, SOCKPERF_TCP)
        if mode == SOCKPERF_TCP:
            return "--tcp"
        return ""

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        if not isinstance(posix_os, BSD) and posix_os.is_package_in_repo("sockperf"):
            posix_os.install_packages("sockperf")
        else:
            packages: List[Union[Type[Tool], str]] = [
                Git,
                Make,
                "automake",
                "m4",
                "autoconf",
                "libtool",
            ]

            if not isinstance(posix_os, BSD):
                # perl already provided by automake for BSD
                packages.append("perl")
                # bsd ships with clang, don't use gcc
                packages.append(Gcc)

            # mariner needs headers and -dev packages
            if isinstance(posix_os, CBLMariner):
                packages.append("build-essential")

            # install and pick build dir
            posix_os.install_packages(packages)

            # bsd ships with clang++, don't use g++
            if not isinstance(posix_os, BSD):
                self.node.tools[Gcc].install_cpp_compiler()

            tool_path = self.get_tool_path()

            git = self.node.tools[Git]
            git.clone(self._sockperf_repo, tool_path)
            code_path = tool_path.joinpath("sockperf")
            # try latest, if fails, try stable
            # seems to work best for BSD+Linux compat for now
            try:
                self.run_build_install(code_path)
            except AssertionError:  # catch build failures
                self.node.tools[Make].run("clean", cwd=code_path, force_run=True)
                # try and older stable tag
                git.checkout(cwd=code_path, ref="3.10")
                self.node.log.debug(
                    "Latest build failed, re-running with stable version 3.10."
                )
                self.run_build_install(code_path)

        # disable any firewalls running which might mess with the test
        self.node.tools[Firewall].stop()

        return self._check_exists()

    def run_build_install(self, code_path: pathlib.PurePath) -> None:
        make = self.node.tools[Make]
        self.node.execute(
            "./autogen.sh",
            shell=True,
            cwd=code_path,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Sockperf: autogen.sh failed after git clone."
            ),
        )

        self.node.execute(
            "./configure --prefix=/usr",
            shell=True,
            cwd=code_path,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Sockperf: ./configure failed after github clone"
            ),
        )

        make.make_install(cwd=code_path, sudo=True)

    def start(self, command: str) -> Process:
        # set higher ulimit value to fix error 'errno=12 Cannot allocate memory'
        # seen on ubuntu 24.10
        return self.node.execute_async(
            f"ulimit -n 65535 && {self.command} {command}", shell=True, sudo=True
        )

    def start_server_async(self, mode: str, timeout: int = 30) -> Process:
        self_ip = self.node.nics.get_primary_nic().ip_addr
        protocol_flag = self._get_protocol_flag(mode)
        return self.start(command=f"server {protocol_flag} -i {self_ip}")

    def run_client_async(self, mode: str, server_ip: str) -> Process:
        protocol_flag = self._get_protocol_flag(mode)
        return self.start(
            command=f"ping-pong {protocol_flag} --full-rtt -i {server_ip}"
        )

    def run_client(self, mode: str, server_ip: str) -> str:
        return self.run_client_async(mode, server_ip).wait_result().stdout

    def create_latency_performance_message(
        self,
        sockperf_output: str,
        test_case_name: str,
        test_result: "TestResult",
    ) -> None:
        matched_results = self.sockperf_result_regex.search(sockperf_output)
        assert matched_results, "Could not find sockperf latency results in output."

        other_fields: Dict[str, Any] = {}
        other_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_SOCKPERF
        other_fields["min_latency_us"] = Decimal(
            matched_results.group("min_latency_us")
        )
        other_fields["max_latency_us"] = Decimal(
            matched_results.group("max_latency_us")
        )
        other_fields["latency99_percentile_us"] = Decimal(
            matched_results.group("latency99_percentile_us")
        )
        self.node.log.info(
            f"sockperf latency results (usec):\n"
            "Percentiles:\n"
            f'MAX   : {matched_results.group("max_latency_us")}\n'
            f'99.999: {matched_results.group("latency99_999_percentile_us")}\n'
            f'99.990: {matched_results.group("latency99_990_percentile_us")}\n'
            f'99.900: {matched_results.group("latency99_900_percentile_us")}\n'
            f'99.000: {matched_results.group("latency99_percentile_us")}\n'
            f'90.000: {matched_results.group("latency_us_90")}\n'
            f'75.000: {matched_results.group("latency_us_75")}\n'
            f'50.000: {matched_results.group("latency_us_50")}\n'
            f'25.000: {matched_results.group("latency_us_25")}\n'
            f'MIN   : {matched_results.group("min_latency_us")}\n'
        )
        message = create_perf_message(
            NetworkLatencyPerformanceMessage,
            self.node,
            test_result,
            test_case_name,
            other_fields,
        )
        notifier.notify(message)

    def get_average_latency(self, sockperf_output: str) -> Decimal:
        matched_results = self.sockperf_average_latency.search(sockperf_output)
        assert matched_results, "Could not find sockperf latency results in output."
        return Decimal(matched_results.group("avg_latency_us"))

    def get_total_observations(self, sockperf_output: str) -> int:
        matched_results = self.sockperf_total_observations.search(sockperf_output)
        assert matched_results, "Could not find sockperf latency results in output."
        return int(matched_results.group("total_observations"))

    def get_run_time(self, sockperf_output: str) -> Decimal:
        matched_results = self.sockperf_run_time.search(sockperf_output)
        assert matched_results, "Could not find sockperf latency results in output."
        return Decimal(matched_results.group("run_time"))

    def get_statistics(self, sockperf_output: str) -> Dict[str, Any]:
        matched_results = self.sockperf_result_regex.search(sockperf_output)
        assert matched_results, "Could not find sockperf latency results in output."
        stats: Dict[str, Any] = {}
        stats["min_latency_us"] = Decimal(matched_results.group("min_latency_us"))
        stats["max_latency_us"] = Decimal(matched_results.group("max_latency_us"))
        stats["average_latency_us"] = self.get_average_latency(sockperf_output)
        stats["latency99_percentile_us"] = Decimal(
            matched_results.group("latency99_percentile_us")
        )
        stats["total_observations"] = self.get_total_observations(sockperf_output)
        stats["run_time_seconds"] = self.get_run_time(sockperf_output)
        return stats
