# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any, Dict

from assertpy import fail

from lisa import (
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import Debian, Fedora
from lisa.tools import Wget

SCRIPT_NAME = "install_script.sh"
PERCENTILE_CHECKER = re.compile(r"95th percentile:\s+(?P<percent_data>[0-9\.]+)")


@TestSuiteMetadata(
    area="memory",
    category="functional",
    description="""
    This test suite runs a basic memory access latency check.
    """,
)
class Memory(TestSuite):
    @TestCaseMetadata(
        description="""
        run a test to measure the memory latency of the node
        """,
        priority=1,
    )
    def verify_memory_latency(
        self, node: RemoteNode, variables: Dict[str, Any]
    ) -> None:
        wget = node.tools[Wget]
        if isinstance(node.os, Debian):
            pkg_type = "deb"
        elif isinstance(node.os, Fedora):
            pkg_type = "rpm"
        else:
            raise SkippedException(
                "This OS is not supported by the memory latency test."
            )

        wget.get(
            (
                "https://packagecloud.io/install/repositories/"
                f"akopytov/sysbench/script.{pkg_type}.sh"
            ),
            filename=SCRIPT_NAME,
            executable=True,
        )

        node.execute(
            f"{node.working_path.joinpath(SCRIPT_NAME)}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to run the sysbench repository add script"
            ),
        )

        node.os.install_packages("sysbench")

        sysbench_result = node.execute(
            (
                "sysbench memory  --memory-access-mode=rnd "
                "--memory-total-size=4G --memory-block-size=512M run"
            )
        )

        percentile_match = PERCENTILE_CHECKER.search(sysbench_result.stdout)
        if percentile_match:
            percent_data = percentile_match.group("percent_data")
            if percent_data:
                if float(percent_data) > 3500.0:
                    fail(
                        (
                            "Latency test failed with loaded latency measurement: "
                            f"{percent_data} (expected under 3500ms)"
                        )
                    )
                else:
                    fail("Could not find latency data in sysbench output!")
