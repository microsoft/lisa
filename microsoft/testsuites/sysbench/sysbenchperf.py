# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any, Dict, List

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.testsuite import TestResult
from lisa.tools import Sysbench


@TestSuiteMetadata(
    area="sysbench",
    category="performance",
    description="""
    This test suite is for executing the sysbench tests
    """,
)
class SysbenchTestSuite(TestSuite):
    @TestCaseMetadata(
        description="""
            Runs Sysbench test for cpu
        """,
        priority=3,
    )
    def perf_sysbench_cpu(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        node.tools[Sysbench].run_cpu_perf(
            test_result=result,
        )

    @TestCaseMetadata(
        description="""
            Runs Sysbench test for fileio
        """,
        priority=3,
    )
    def perf_sysbench_fileio(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        io_ops = variables.get(
            "io_ops",
            [
                "seqwr",
                "seqrd",
                "rndrd",
                "rndwr",
                "seqrewr",
                "rndrw",
            ],
        )
        sysbench = node.tools[Sysbench]
        sysbench.run_fileio_perf(
            test_result=result,
            total_file=1,
            io_ops=io_ops,
        )

    @TestCaseMetadata(
        description="""
            Runs Sysbench test for memory
        """,
        priority=3,
    )
    def perf_sysbench_memory(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        memory_operation: List[str] = variables.get(
            "memory_operation",
            [
                "read",
                "write",
            ],
        )
        memory_access_mode: List[str] = variables.get(
            "memory_access_mode",
            [
                "seq",
                "rnd",
            ],
        )
        node.tools[Sysbench].run_memory_perf(
            test_result=result,
            memory_access_mode=memory_access_mode,
            memory_oper=memory_operation,
        )
