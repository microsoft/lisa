# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import itertools
import json
import os
import pathlib
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, List, Tuple, Type

from assertpy import assert_that

from lisa.executable import Tool
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.node import Node
from lisa.operating_system import Posix
from lisa.testsuite import TestResult
from lisa.tools.echo import Echo
from lisa.tools.git import Git
from lisa.tools.nvidiasmi import NvidiaSmi
from lisa.tools.whoami import Whoami

import yaml

@dataclass
class SuperbenchResult:
    version: str = ""
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    exit_value: int = 0

class Superbench(Tool):
    @property
    def command(self) -> str:
        return "/usr/bin/sb"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def repo_url(self) -> str:
        return self._sb_repo

    @property
    def sb_install_path(self) -> str:
        return f"{self.node.tools[Whoami].get_username()}/superbench"

    @property
    def sb_docker_image(self) -> str:
        return f"superbench/superbench:{self._sb_container_tag}"


    @property
    def sb_config(self) -> str:
        if not self._sb_config:
            # Template substitute superbench config, for now only "NUM_GPU" is relevant
            sb_config_tpt =  pathlib.PurePath(__file__).parent.joinpath("configs", self._sb_config_tpt)
            sb_cfg = open(sb_config_tpt).read()

            gpu_count = self.node.tools[NvidiaSmi].get_gpu_count()
            sb_cfg = sb_cfg.format(NUM_GPU=gpu_count)

            sb_cfg_tempdir = tempfile.mkdtemp()
            sb_cfg_temp = pathlib.joinpath(sb_cfg_tempdir, self._sb_config_tpt)
            with open(sb_cfg_temp, "w") as cfg_file:
                cfg_file.write(sb_cfg)
            self._sb_config = sb_cfg_temp
        return self._sb_config

    def __init__(self, node: Node, source_file: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(node, args, kwargs)
        self._sb_repo = kwargs["sb_repo"]
        self._sb_branch = kwargs["sb_branch"]
        self._sb_config_tpt = kwargs["sb_config"]
        self._sb_image_tag = kwargs["sb_image_tag"]

        self._sb_config = ""

    def run_test(
        self,
        test_result: TestResult,
        log_path,
        sb_run_timeout: int = 1800,
    ) -> List[SuperbenchResult]:

        # run superbench tests
        sb_cfg_filename = os.path.basename(self.sb_config)
        command = f"{self.command} run -f local.ini -c ./{sb_cfg_filename}"
        self.node.execute(command, shell=True,
                          cwd=self.sb_install_path,
                          timeout=sb_run_timeout)

        # tar gzip result directory and copy to local machine
        sb_local_result_tgz = pathlib.joinpath(log_path, "outputs.tgz")
        self.node.execute("tar -czf outputs.tgz outputs",
                          cwd=self.sb_install_path, timeout=sb_run_timeout)
        self.node.shell.copy_back(pathlib.joinpath(self.sb_install_path, "outputs.tgz"),
                                  sb_local_result_tgz)

        passed_tests, failed_tests = self.parse_results(sb_local_result_tgz)
        for result in itertools.chain(passed_tests, failed_tests):
            # create test result message
            info: Dict[str, Any] = {}
            info["information"] = {}
            info["information"]["version"] = result.version
            info["information"]["exit_value"] = result.exit_value
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=result.name,
                test_status=result.status,
                other_fields=info,
            )

        # assert that none of the tests failed
        assert_that(
            failed_tests, f"The following tests failed: {failed_tests}"
        ).is_empty()

        return passed_tests + failed_tests

    @staticmethod
    def get_enabled_tests(sb_cfg_yaml):
        with open(sb_cfg_yaml, "r") as yaml_file:
            sb_config = yaml.safe_load(yaml_file)

        # Extract entries under superbench.enable
        enabled_tests = sb_config.get("superbench", {}).get("enable", [])

        return enabled_tests

    def group_result_by_test(self, jsonl_file: str, tests: list[str]) -> Dict[str, Dict[str, int]]:
        test_results = {test_name : {} for test_name in tests}

        result_entries = json.load(open(jsonl_file))
        for key, value in result_entries.items():
            test_name, subtext = key.split("/", 1)
            test_results[test_name][subtext] = value

        return test_results

    @staticmethod
    def split_result(result_group: Dict[str, Dict[str, int]]) -> Tuple[Dict[str, int], Dict[str, int]]:
        failed_tests = []
        passed_tests = []
        for test_name, test_results in result_group.items():
            test_return_codes = [v for k, v in test_results.items() if k.startswith("return_code")]
            result_object = SuperbenchResult(name=test_name, status=TestStatus.PASSED, exit_value=0)
            if any(test_return_codes):
                result_object.status = TestStatus.FAILED
                result_object.exit_value = max(test_return_codes)
                failed_tests.append(result_object)
            else:
                passed_tests.append(result_object)
        return passed_tests, failed_tests

    def parse_results(self, sb_result_tgz):
        sb_result_tgz = Path(sb_result_tgz)
        result_dir = pathlib.joinpath(sb_result_tgz.parent, "outputs")

        subprocess.run(["tar", "zxf", sb_result_tgz.name],
                       check=True, cwd=result_dir)

        result_dir = os.listdir(result_dir)[0]
        cfg_yaml = pathlib.joinpath(result_dir, "sb.confilename")
        result_json = pathlib.joinpath(result_dir, "results-summary.jsonl")

        enabled_tests = self.get_enabled_tests(cfg_yaml)
        result_groups = self.group_result_by_test(result_json, enabled_tests)

        return self.split_result(result_groups)

    def _install(self) -> bool:
        assert isinstance(self.node.os, Posix), f"{self.node.os} is not supported"

        # Install host packages, superbench container is self contained
        self.node.os.install_packages(["lshw", "rsync"])

        # Clone superbench repo, switch to chosen branch
        git = self.node.tools[Git]
        git.clone(self.repo_url, self.sb_install_path)
        git.checkout(self.sb_branch, self.sb_install_path)

        # Create local ini file to deploy sb, that includes pulling ubuntu superbench container
        self.node.tools[Echo].write_to_file("[all]\nlocalhost ansible_connection=local",
                                       os.path.join(self.sb_install_path, "local.ini"))

        # setup superbench
        self.node.execute("python3 -m pip install .", cwd=self.sb_install_path)
        self.node.execute("make postinstall", cwd=self.sb_install_path)
        self.node.execute(f"sb deploy -f local.ini -i {self.sb_docker_image}",
                          cwd=self.sb_install_path)

        sb_cfg_filename = os.path.basename(self.sb_config)
        self.node.copy_to_remote(self.sb_config,
                                 pathlib.joinpath(self.sb_install_path, sb_cfg_filename))

        return self._check_exists()
