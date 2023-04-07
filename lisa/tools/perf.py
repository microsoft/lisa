# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, CentOs, Posix, Redhat
from lisa.tools import Uname
from lisa.util import SkippedException, find_patterns_in_lines


class Perf(Tool):
    # Total time: 71.514 [sec]
    PERF_MESSAGING_RESULT = re.compile(r"Total time: (?P<time>\d+\.\d+) \[sec\]", re.M)
    PERF_EPOLL_RESULT = re.compile(r"Averaged (?P<time>\d+) operations/sec", re.M)

    @property
    def command(self) -> str:
        return "perf"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        assert isinstance(self.node.os, Posix), f"{self.node.os} is not supported"
        if not self._check_exists():
            kernel_ver = (
                self.node.tools[Uname].get_linux_information().kernel_version_raw
            )
            if (
                isinstance(self.node.os, Redhat)
                or isinstance(self.node.os, CentOs)
                or isinstance(self.node.os, CBLMariner)
            ):
                self.node.os.install_packages("perf")
            else:
                self.node.os.install_packages(
                    [
                        "linux-tools-common",
                        "linux-tools-generic",
                        f"linux-tools-{kernel_ver}",
                    ]
                )
        return self._check_exists()

    def perf_messaging(self) -> List[float]:
        # Link to the source code:
        # https://github.com/torvalds/linux/blob/master/tools/perf/bench/sched-messaging.c # noqa: E501
        # Run it 20 times to get stable result
        results = []
        for _ in range(20):
            result = self._run_perf("bench sched messaging -l 10000")

            # Example output:
            # Running 'sched/messaging' benchmark:
            # 20 sender and receiver processes per group
            # 10 groups == 400 processes run
            # Total time: 71.514 [sec]
            matched = find_patterns_in_lines(result, [self.PERF_MESSAGING_RESULT])
            results.append(float(matched[0][0]))

        return results

    def perf_epoll(self) -> List[float]:
        # Link to the source code:
        # https://github.com/torvalds/linux/blob/master/tools/perf/bench/epoll-wait.c # noqa: E501
        # Run it 20 times to get stable result
        results = []
        for _ in range(20):
            result = self._run_perf("bench epoll wait", sudo=True)

            # Example output:
            # Running epoll/wait benchmark...
            # Run summary [PID 5355]: 1 threads monitoring on
            # 64 file-descriptors for 8 secs.
            # [thread  0] fdmap: 0x55cf02189eb0 ... 0x55cf02189fac [ 544357 ops/sec ]
            # Averaged 544357 operations/sec (+- 0.00%), total secs = 8
            # ...
            matched = find_patterns_in_lines(result, [self.PERF_EPOLL_RESULT])
            results.append(float(matched[0][0]))

        return results

    def _run_perf(self, command: str, sudo: bool = False) -> str:
        result = self.run(command, force_run=True, sudo=sudo)
        if result.exit_code != 0:
            # check if epoll is not supported by the perf tool version
            if "Unknown collection" in result.stdout:
                raise SkippedException(
                    f"perf {command} is not supported on this distro"
                )
            result.assert_exit_code(message=result.stdout)
        return result.stdout
