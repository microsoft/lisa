# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, Dict

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata, notifier
from lisa.messages import (
    DescriptorPollThroughput,
    IPCLatency,
    create_perf_message,
    send_unified_perf_message,
)
from lisa.operating_system import BSD, Windows
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Perf


@TestSuiteMetadata(
    area="perf_tool",
    category="performance",
    description="""
    This test suite is to generate performance data with perf tool.
    """,
)
class PerfToolSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case uses perf tool to measure the messaging performance.
        The steps are:
        1. Run perf messaging benchmark 20 times.
        3. Calculate the average, min, max time of the 20 runs.
        """,
        priority=3,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_messaging(
        self,
        node: Node,
        result: TestResult,
    ) -> None:
        perf_tool = node.tools[Perf]
        perf_results = perf_tool.perf_messaging()
        # Calculate metrics
        metrics = {
            "average_time_sec": sum(perf_results) / len(perf_results),
            "min_time_sec": min(perf_results),
            "max_time_sec": max(perf_results),
        }
        self._create_and_notify_perf_message(
            IPCLatency,
            node,
            result,
            "perf_messaging",
            metrics,
        )

    @TestCaseMetadata(
        description="""
        This test case uses perf tool to measure the epoll performance.
        The steps are:
        1. Run perf epoll benchmark 20 times.
        3. Calculate the average, min, max operations of the 20 runs.
        """,
        priority=3,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_epoll(
        self,
        node: Node,
        result: TestResult,
    ) -> None:
        perf_tool = node.tools[Perf]
        perf_results = perf_tool.perf_epoll()
        metrics = {
            "average_ops": sum(perf_results) / len(perf_results),
            "min_ops": min(perf_results),
            "max_ops": max(perf_results),
        }
        self._create_and_notify_perf_message(
            DescriptorPollThroughput,
            node,
            result,
            "perf_epoll",
            metrics,
        )

    def _create_and_notify_perf_message(
        self,
        message_type: type,
        node: Node,
        result: TestResult,
        test_case_name: str,
        metrics: Dict[str, Any],
    ) -> None:
        tool = "perf"
        other_fields: Dict[str, Any] = metrics.copy()
        other_fields["tool"] = tool
        message = create_perf_message(  # type: ignore
            message_type,
            node,
            result,
            test_case_name,
            other_fields,
        )
        notifier.notify(message)

        for key, value in metrics.items():
            send_unified_perf_message(
                node=node,
                test_result=result,
                test_case_name=test_case_name,
                tool=tool,
                metric_name=key,
                metric_value=value,
            )
