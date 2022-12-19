# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, List, Optional, Type

from assertpy.assertpy import assert_that, fail

from lisa import Environment, notifier
from lisa.executable import Tool
from lisa.features import SerialConsole
from lisa.messages import SubTestMessage, TestStatus, create_test_result_message
from lisa.operating_system import CBLMariner
from lisa.testsuite import TestResult
from lisa.tools import Dmesg, Docker, Echo, Git, Whoami


@dataclass
class CloudHypervisorTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED


class CloudHypervisorTests(Tool):
    CMD_TIME_OUT = 7200
    # Slightly higher case timeout to give the case a window to extract
    # sub test results from stdout and report them.
    CASE_TIME_OUT = CMD_TIME_OUT + 300

    repo = "https://github.com/cloud-hypervisor/cloud-hypervisor.git"

    cmd_path: PurePath
    repo_root: PurePath

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Docker]

    def run_tests(
        self,
        test_result: TestResult,
        environment: Environment,
        test_type: str,
        hypervisor: str,
        log_path: Path,
        skip: Optional[List[str]] = None,
    ) -> None:

        if skip is not None:
            skip_args = " ".join(map(lambda t: f"--skip {t}", skip))
        else:
            skip_args = ""

        result = self.run(
            f"tests --hypervisor {hypervisor} --{test_type} -- -- {skip_args}"
            " -Z unstable-options --format json",
            timeout=self.CMD_TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,  # print out result of each test
            shell=True,
        )

        # Report subtest results and collect logs before doing any
        # assertions.
        results = self._extract_test_results(result.stdout, log_path)
        failures = [r.name for r in results if r.status == TestStatus.FAILED]

        for r in results:
            self._send_subtest_msg(
                test_result,
                environment,
                r.name,
                r.status,
            )

        self._save_kernel_logs(log_path)

        has_failures = len(failures) > 0
        if result.is_timeout and has_failures:
            fail(
                f"Timed out after {result.elapsed:.2f}s "
                f"with unexpected failures: {failures}"
            )
        elif result.is_timeout:
            fail(f"Timed out after {result.elapsed:.2f}s")
        elif has_failures:
            fail(f"Unexpected failures: {failures}")
        else:
            # The command could have failed before starting test case execution.
            # So, check the exit code too.
            result.assert_exit_code()

    def run_metrics_tests(
        self,
        test_result: TestResult,
        environment: Environment,
        hypervisor: str,
        log_path: Path,
        skip: Optional[List[str]] = None,
    ) -> None:
        perf_metrics_tests = self._list_perf_metrics_tests(hypervisor=hypervisor)
        failed_testcases = []

        for testcase in perf_metrics_tests:
            testcase_log_file = log_path.joinpath(f"{testcase}.log")

            status: TestStatus = TestStatus.QUEUED
            metrics: str = ""
            trace: str = ""
            try:
                result = self.run(
                    f"tests --hypervisor {hypervisor} --metrics -- -- \
                        --test-filter {testcase}",
                    timeout=self.CMD_TIME_OUT,
                    force_run=True,
                    cwd=self.repo_root,
                    no_info_log=False,  # print out result of each test
                    shell=True,
                    update_envs={"RUST_BACKTRACE": "full"},
                )

                if result.exit_code == 0:
                    status = TestStatus.PASSED
                    metrics = self._process_perf_metric_test_result(result.stdout)
                else:
                    status = TestStatus.FAILED
                    trace = f"Testcase '{testcase}' failed: {result.stderr}"
                    failed_testcases.append(testcase)

            except Exception as e:
                self._log.info(f"Testcase failed, tescase name: {testcase}")
                status = TestStatus.FAILED
                trace = str(e)
                failed_testcases.append(testcase)

            msg = metrics if status == TestStatus.PASSED else trace
            self._send_subtest_msg(
                test_result,
                environment,
                testcase,
                status,
                msg,
            )

            # Write stdout of testcase to log as per given requirement
            with open(testcase_log_file, "w") as f:
                f.write(result.stdout)

        self._save_kernel_logs(log_path)

        assert_that(
            failed_testcases, f"Failed Testcases: {failed_testcases}"
        ).is_empty()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path / "cloud-hypervisor"
        self.cmd_path = self.repo_root / "scripts" / "dev_cli.sh"

    def _install(self) -> bool:
        git = self.node.tools[Git]
        git.clone(self.repo, self.get_tool_path(use_global=True))
        if isinstance(self.node.os, CBLMariner):
            daemon_json_file = PurePath("/etc/docker/daemon.json")
            daemon_json = '{"default-ulimits":{"nofile":{"Hard":65535,"Name":"nofile","Soft":65535}}}'  # noqa: E501
            self.node.tools[Echo].write_to_file(
                daemon_json, daemon_json_file, sudo=True
            )

        self.node.execute("groupadd -f docker", expected_exit_code=0)
        username = self.node.tools[Whoami].get_username()
        res = self.node.execute("getent group docker", expected_exit_code=0)
        if username not in res.stdout:  # if current user is not in docker group
            self.node.execute(f"usermod -a -G docker {username}", sudo=True)
            # reboot for group membership change to take effect
            self.node.reboot()

        self.node.tools[Docker].start()

        return self._check_exists()

    def _extract_test_results(
        self, output: str, log_path: Path
    ) -> List[CloudHypervisorTestResult]:
        results: List[CloudHypervisorTestResult] = []

        # Cargo will output test status for each test separately in JSON format. Parse
        # the output line by line to obtain the list of all tests run along with their
        # outcomes.
        #
        # Example output:
        # { "type": "test", "event": "ok", "name": "integration::test_vfio" }
        lines = output.split("\n")
        for line in lines:
            result = {}
            try:
                result = json.loads(line)
            except json.decoder.JSONDecodeError:
                continue

            if type(result) is not dict:
                continue

            if "type" not in result or result["type"] != "test":
                continue

            if "event" not in result or result["event"] not in ["ok", "failed"]:
                continue

            status = TestStatus.PASSED if result["event"] == "ok" else TestStatus.FAILED
            results.append(
                CloudHypervisorTestResult(
                    name=result["name"],
                    status=status,
                )
            )

            # store stdout of failed subtests
            if status == TestStatus.FAILED:
                # test case names have ':'s in them (e.g. "integration::test_vfio").
                #  ':'s are not allowed in file names in Windows.
                testcase = result["name"].replace(":", "-")
                testcase_log_file = log_path / f"{testcase}.log"
                with open(testcase_log_file, "w") as f:
                    f.write(result["stdout"])

        return results

    def _send_subtest_msg(
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

    def _list_perf_metrics_tests(self, hypervisor: str = "kvm") -> List[str]:

        tests_list = []
        result = self.run(
            f"tests --hypervisor {hypervisor} --metrics -- -- --list-tests",
            timeout=self.CMD_TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            shell=True,
            expected_exit_code=0,
        )

        stdout = result.stdout

        # Ex. String for below regex
        # "boot_time_ms" (test_timeout=2s,test_iterations=10)
        regex = '\\"(.*)\\" \\('

        pattern = re.compile(regex)
        tests_list = pattern.findall(stdout)

        self._log.debug(f"Testcases found: {tests_list}")
        return tests_list

    def _process_perf_metric_test_result(self, output: str) -> str:

        # Sample Output
        # "git_human_readable": "v27.0",
        # "git_revision": "2ba6a9bfcfd79629aecf77504fa554ab821d138e",
        # "git_commit_date": "Thu Sep 29 17:56:21 2022 +0100",
        # "date": "Wed Oct 12 03:51:38 UTC 2022",
        # "results": [
        #     {
        #     "name": "block_multi_queue_read_MiBps",
        #     "mean": 158.64382311768824,
        #     "std_dev": 7.685502103050337,
        #     "max": 173.9743994350565,
        #     "min": 154.10646435356466
        #     }
        # ]
        # }
        # real    1m39.856s
        # user    0m6.376s
        # sys     2m32.973s
        # + RES=0
        # + exit 0

        output = output.replace("\n", "")
        regex = '\\"results\\"\\: (.*?)\\]'
        result = re.search(regex, output)
        if result:
            return result.group(0)
        return ""

    def _save_kernel_logs(self, log_path: Path) -> None:
        # Use serial console if available. Serial console logs can be obtained
        # even if the node goes down (hung, panicked etc.). Whereas, dmesg
        # can only be used if node is up and LISA is able to connect via SSH.
        if self.node.features.is_supported(SerialConsole):
            serial_console = self.node.features[SerialConsole]
            serial_console.get_console_log(log_path, force_run=True)
        else:
            dmesg_str = self.node.tools[Dmesg].get_output(force_run=True)
            dmesg_path = log_path / "dmesg"
            with open(str(dmesg_path), "w") as f:
                f.write(dmesg_str)
