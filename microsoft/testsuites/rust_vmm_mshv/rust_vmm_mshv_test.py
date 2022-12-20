# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path

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
from lisa.testsuite import TestResult
from lisa.tools import Cargo, Git
from lisa.util.process import ExecutableResult


@TestSuiteMetadata(
    area="rust-vmm",
    category="community",
    description="""
    This test suite is for executing the rust-vmm/mshv tests
    """,
)
class RustVmmTestSuite(TestSuite):
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
        # node.tools[RustVmmTests].run_rust_vmm_mshv_tests(
        #     result, environment, "integration", hypervisor, log_path
        # )
        repo = "https://github.com/rust-vmm/mshv.git"
        git = node.tools[Git]
        repo_root = git.clone(repo, node.get_working_path())
        testcase_log = log_path.joinpath("rust_vmm_mshv.log")

        cargo = node.tools[Cargo]
        test_result: ExecutableResult = cargo.test(cwd=repo_root, sudo=True)

        with open(testcase_log, "w") as f:
            f.write(f"{test_result.stdout} {test_result.stderr}")

        self.__process_result(
            test_result.stdout,
            result,
            environment,
            node,
        )

    def __process_result(
        self,
        data: str,
        result: TestResult,
        environment: Environment,
        node: Node,
    ) -> None:

        pattern = r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
        ansi_escape = re.compile(pattern)
        data = ansi_escape.sub('', data)

        match = re.findall(
            r"test (.*?) ... (ok|ignored|failed)(.*?)\n",
            data,
            re.IGNORECASE,
        )

        failed_testcases = []
        for testcase in match:
            status = TestStatus.QUEUED
            testcase_name = testcase[0]
            if (testcase[-2] and testcase[-2].strip().lower() == "ok"):
                status = TestStatus.PASSED
            elif (testcase[-2] and testcase[-2].strip().lower() == "failed"):
                failed_testcases.append(testcase_name)
                status = TestStatus.FAILED
            elif (testcase[-2] and testcase[-2].strip().lower() == "ignored"):
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
