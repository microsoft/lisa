# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata, notifier
from lisa.messages import DescriptorPollThroughput, IPCLatency, create_perf_message
from lisa.testsuite import TestResult
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
    )
    def perf_messaging(
        self,
        node: Node,
        result: TestResult,
    ) -> None:
        perf_tool = node.tools[Perf]
        perf_results = perf_tool.perf_messaging()
        other_fields = {}
        other_fields["average_time_sec"] = sum(perf_results) / len(perf_results)
        other_fields["min_time_sec"] = min(perf_results)
        other_fields["max_time_sec"] = max(perf_results)
        message = create_perf_message(
            IPCLatency,
            node,
            result,
            self.__class__.__name__,
            other_fields,
        )
        notifier.notify(message)

    @TestCaseMetadata(
        description="""
        This test case uses perf tool to measure the epoll performance.
        The steps are:
        1. Run perf epoll benchmark 20 times.
        3. Calculate the average, min, max operations of the 20 runs.
        """,
        priority=3,
    )
    def perf_epoll(
        self,
        node: Node,
        result: TestResult,
    ) -> None:
        perf_tool = node.tools[Perf]
        perf_results = perf_tool.perf_epoll()
        other_fields = {}
        other_fields["average_ops"] = sum(perf_results) / len(perf_results)
        other_fields["min_ops"] = min(perf_results)
        other_fields["max_ops"] = max(perf_results)
        message = create_perf_message(
            DescriptorPollThroughput,
            node,
            result,
            self.__class__.__name__,
            other_fields,
        )
        notifier.notify(message)
