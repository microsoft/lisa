# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path
from typing import Any

from assertpy.assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    notifier,
)
from lisa.messages import SubTestMessage, TestStatus, create_test_result_message
from lisa.operating_system import BSD, Windows
from lisa.testsuite import TestResult
from lisa.tools import Cargo, Git, Ls
from lisa.util import SkippedException
from lisa.util.process import ExecutableResult


@TestSuiteMetadata(
    area="rust-vmm",
    category="community",
    description="""
    This test suite is for executing the rust-vmm/mshv tests
    """,
)
class RustVmmTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")

        mshv_exists = node.tools[Ls].path_exists(path="/dev/mshv", sudo=True)
        if not mshv_exists:
            raise SkippedException(
                "Rust Vmm MSHV test can be run with MSHV wrapper (/dev/mshv) only."
            )

    @TestCaseMetadata(
        description="""
            Runs rust-vmm/mshv tests
        """,
        priority=3,
        timeout=1800,
    )
    def verify_rust_vmm_mshv_tests(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
    ) -> None:
        repo = "https://github.com/rust-vmm/mshv.git"
        git = node.tools[Git]
        repo_root = git.clone(repo, node.get_working_path())
        testcase_log = log_path / "rust_vmm_mshv.log"
        cargo = node.tools[Cargo]
        test_result: ExecutableResult = cargo.test(cwd=repo_root, sudo=True)
        with open(testcase_log, "w") as f:
            f.write(f"{test_result.stdout} {test_result.stderr}")
        self.__process_result(
            test_result.stdout,
            result,
            environment,
        )

    def __process_result(
        self,
        data: str,
        result: TestResult,
        environment: Environment,
    ) -> None:
        pattern = r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
        ansi_escape = re.compile(pattern)
        data = ansi_escape.sub("", data)
        match = re.findall(
            r"test (.*?) ... (ok|ignored|failed)(.*?)\n",
            data,
            re.IGNORECASE,
        )
        failed_testcases = []
        for testcase in match:
            status = TestStatus.QUEUED
            testcase_name = testcase[0]
            log_status = testcase[-2]
            if log_status and log_status.strip().lower() == "ok":
                status = TestStatus.PASSED
            elif log_status and log_status.strip().lower() == "failed":
                failed_testcases.append(testcase_name)
                status = TestStatus.FAILED
            elif log_status and log_status.strip().lower() == "ignored":
                status = TestStatus.SKIPPED
            self.__send_subtest_msg(
                result,
                environment,
                testcase_name,
                status,
            )
        assert_that(
            failed_testcases, f"Failed Testcases: {failed_testcases}"
        ).is_empty()

    def __send_subtest_msg(
        self,
        test_result: TestResult,
        environment: Environment,
        test_name: str,
        test_status: TestStatus,
        test_message: str = "",
    ) -> None:
        subtest_msg = create_test_result_message(
            SubTestMessage,
            test_result,
            environment,
            test_name,
            test_status,
            test_message,
        )
        notifier.notify(subtest_msg)
