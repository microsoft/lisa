# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, cast

from assertpy import assert_that

from lisa import notifier
from lisa.executable import Tool
from lisa.messages import NetworkLatencyPerformanceMessage, create_perf_message
from lisa.operating_system import BSD, CBLMariner, Posix
from lisa.tools import Gcc, Git, Make
from lisa.util import constants
from lisa.util.process import Process

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
        # FIXME: bug in BSD bulld is blocking BSD runs.
        # Fast fail if attempting ot install.
        return self.node.is_posix

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
            packages: List[type[Tool] | str] = [
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

        return self._check_exists()

    def get(self, command: str) -> str:
        return self.run(command, shell=True, force_run=True).stdout

    def start(self, command: str) -> Process:
        return self.run_async(command, shell=True, force_run=True)

    def start_server(self, mode: str, timeout: int = 30) -> Process:
        self_ip = self.node.nics.get_primary_nic().ip_addr
        protocol_flag = self._get_protocol_flag(mode)
        return self.start(command=f"server {protocol_flag} -i {self_ip}")

    def run_client(self, mode: str, server_ip: str) -> str:
        protocol_flag = self._get_protocol_flag(mode)
        return self.get(f"ping-pong {protocol_flag} --full-rtt -i {server_ip}")

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
            f'MAX   :  {matched_results.group("max_latency_us")}\n'
            f'99.999: {matched_results.group("latency99_999_percentile_us")}\n'
            f'99.990: {matched_results.group("latency99_990_percentile_us")}\n'
            f'99.900: {matched_results.group("latency99_900_percentile_us")}\n'
            f'99.000: {matched_results.group("latency99_percentile_us")}\n'
            f'90.000: {matched_results.group("latency_us_90")}\n'
            f'75.000: {matched_results.group("latency_us_75")}\n'
            f'50.000: {matched_results.group("latency_us_50")}\n'
            f'25.000: {matched_results.group("latency_us_25")}\n'
            f'MIN   :  {matched_results.group("min_latency_us")}\n'
        )
        message = create_perf_message(
            NetworkLatencyPerformanceMessage,
            self.node,
            test_result,
            test_case_name,
            other_fields,
        )
        notifier.notify(message)
