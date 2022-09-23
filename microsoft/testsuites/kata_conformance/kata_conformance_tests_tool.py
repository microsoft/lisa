# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, List, Type

from kubernetes import client, config, utils

from lisa import Environment, notifier
from lisa.executable import Tool
from lisa.messages import SubTestMessage, TestStatus, create_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import Echo, Git, Go, Make
from lisa.util import LisaException


@dataclass
class KataConformanceTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED


class KataConformanceTests(Tool):
    # These tests take some time to finish executing. The default
    # timeout of 600 is not sufficient.
    TIME_OUT = 18000

    cmd_path: PurePath
    cmd_args: str
    repo_root: PurePath
    kube_config_path: PurePath

    kubernetes_repo = "https://github.com/kubernetes/kubernetes.git"
    kata_container_tests_repo = "https://github.com/kata-containers/tests.git"
    deps = ["git", "make"]

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make, Go]

    def run_tests(
        self, test_result: TestResult, environment: Environment, failure_logs_path: Path
    ) -> None:
        echo = self.node.tools[Echo]
        original_path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout
        new_path = f"/usr/local/go/bin/:{original_path}"
        self._log.info("Before run_tests : New Path : " + str(new_path))

        exec_result = self.run(
            self.cmd_args,
            timeout=self.TIME_OUT,
            sudo=True,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,  # print out result of each test
            update_envs={"PATH": new_path},
        )

        self._log.info("Exit code of run_tests : " + str(exec_result.exit_code))

        results = self._parse_results(self.report_path.joinpath("json_report.json"))

        failed_tests = []
        for result in results:
            if result.status == TestStatus.FAILED:
                failed_tests.append(result.name)
            subtest_message = create_test_result_message(
                SubTestMessage,
                test_result.id_,
                environment,
                result.name,
                result.status,
            )

            notifier.notify(subtest_message)

    def _parse_results(self, report_filename: str) -> List[KataConformanceTestResult]:

        results: List[KataConformanceTestResult] = []
        testcases = None

        if not os.path.exists(report_filename):
            raise LisaException("Can not find report file : " + str(report_filename))

        with open(report_filename, "r") as f:
            data = f.read()
            testcases = json.loads(data)

        for testcase in testcases[0]["SpecReports"]:
            result = KataConformanceTestResult()
            result.name = testcase["LeafNodeText"]

            if testcase["State"] == "passed":
                result.status = TestStatus.PASSED
            elif testcase["State"] == "failed":
                result.status = TestStatus.FAILED
            else:
                result.status = TestStatus.SKIPPED

            results.append(result)

        return results

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path.joinpath("kata-conformance-test")
        if not os.path.exists(self.repo_root):
            os.mkdir(self.repo_root)
        self.cmd_path = self.repo_root.joinpath("""kubernetes/_output/bin/e2e.test""")
        self.report_path = self.repo_root.joinpath("report")
        if not os.path.exists(self.report_path):
            os.mkdir(self.report_path)
        self.kube_config_path = os.environ.get("KUBECONFIG", None)
        args = ""
        args = args + f"-kubeconfig {self.kube_config_path} "
        args = args + '--ginkgo.focus="\[Conformance\]" '
        args = args + "--ginkgo.timeout 5h "
        report_path = str(self.report_path.joinpath("json_report.json"))
        args = args + f"--ginkgo.json-report {report_path} "
        self.cmd_args = args

        self._install()

    def _install_dep(self) -> None:
        git = self.node.tools[Git]
        self._log.info("Cloning Repo : " + self.kubernetes_repo)
        git.clone(self.kubernetes_repo, self.repo_root, timeout=3600)
        self._log.info("Cloning Repo : " + self.kata_container_tests_repo)
        git.clone(self.kata_container_tests_repo, self.repo_root, timeout=3600)

        self._log.info("Installing GoLang")
        go = self.node.tools.get(Go, go_version="1.19")
        self._log.info("Installed GoLang version -> " + go.get_version())

    def _create_kata_webhook(self) -> None:
        kube_config = os.environ.get("KUBECONFIG", None)

        if kube_config:

            # Load Kube config
            config.load_kube_config()

            # Create Client to perform kubernetes actions
            k8s_client = client.ApiClient()

            # runtime_class.yaml : Create runtime class to set kata container runtime
            # create_pod.yaml : Create dummy pod with runtime class
            yaml_files = ["runtime_class.yaml", "create_pod.yaml"]
            for file in yaml_files:
                abs_file_path = os.path.join(
                    os.path.abspath(__file__).replace(os.path.basename(__file__), ""),
                    file,
                )
                self._log.debug(f"Running : {abs_file_path}")
                utils.create_from_yaml(k8s_client, abs_file_path, verbose=True)
                self._log.debug(f"Done with running : {abs_file_path}")

            # Create Kata webhook
            if os.path.isfile(
                self.repo_root.joinpath("tests/kata-webhook/deploy/webhook.yaml")
            ):

                # Exclude kube-system name space while creating webhook
                self._log.debug("exclude-namespaces : Updating webhook.yaml")
                data = ""

                with open(
                    self.repo_root.joinpath("tests/kata-webhook/deploy/webhook.yaml"),
                    "r",
                ) as f:
                    data = f.read()
                    data = data.replace(
                        "exclude-namespaces=rook-ceph-system,rook-ceph",
                        "exclude-namespaces=kube-system",
                    )

                with open(
                    self.repo_root.joinpath("tests/kata-webhook/deploy/webhook.yaml"),
                    "w",
                ) as f:
                    f.write(data)
                self._log.debug("exclude-namespaces : Updated webhook.yaml")

                # Create config map
                abs_file_path = os.path.join(
                    os.path.abspath(__file__).replace(os.path.basename(__file__), ""),
                    "config_map.yaml",
                )

                self._log.debug(f"Running {abs_file_path}")
                utils.create_from_yaml(k8s_client, abs_file_path, verbose=True)
                self._log.debug(f"Done with running {abs_file_path}")

                # Run create_certs.sh
                cert_sh_path = self.repo_root.joinpath("tests/kata-webhook")
                command = cert_sh_path.joinpath("create-certs.sh")
                self._log.debug(f"Running {command}")
                self.node.execute(command, cwd=cert_sh_path, shell=True, sudo=False)
                self._log.debug(f"Done with running {cert_sh_path}")

                # Deploy the webhook
                deploy_webhook = self.repo_root.joinpath(
                    "tests/kata-webhook/deploy/webhook.yaml"
                )
                self._log.debug(f"Deploying webhook : {deploy_webhook}")
                utils.create_from_yaml(k8s_client, deploy_webhook, verbose=True)
                self._log.debug(f"Done with deploying webhook : {deploy_webhook}")

                # Check the webhook
                self._log.debug("Checking webhook")
                webhook_check_sh = self.repo_root.joinpath(
                    "tests/kata-webhook/webhook-check.sh"
                )
                self.node.execute(webhook_check_sh, shell=True, sudo=False)
                self._log.debug("Done with checking webhook")

            else:
                raise LisaException("Can not find webhook.yaml file")
        else:
            raise LisaException("Can not find kubeconfig file")

    def _install(self) -> bool:
        self._log.info("Installing dependency for kata-conformance-tests")
        self._install_dep()
        self._log.info("Done installing dependency for kata-conformance-tests")

        self._log.info("Configuring Kata Webhook")
        self._create_kata_webhook()
        self._log.info("Kata Webhook configured")

        make = self.node.tools[Make]

        # run make in the repo
        self._log.debug("Building Kubernetes")
        kubernetes_path = self.repo_root.joinpath("kubernetes")

        echo = self.node.tools[Echo]
        original_path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout
        new_path = f"/usr/local/go/bin/:{original_path}"
        self._log.debug("Before Make : New Path : " + str(new_path))

        make.make(
            "WHAT=test/e2e/e2e.test",
            kubernetes_path,
            timeout=self.TIME_OUT,
            update_envs={"PATH": new_path},
        )
        self._log.debug("Finished building Kubernetes")

        return self._check_exists()
