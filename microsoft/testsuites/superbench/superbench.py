# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import itertools
import json
import yaml
import os
import subprocess
import tempfile

from dataclasses import dataclass
from pathlib import Path, PurePath, PosixPath
from typing import Any, Dict, List, Tuple, Type
from datetime import datetime

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
from lisa.tools.chmod import Chmod
from lisa.tools import RemoteCopy

@dataclass
class SuperbenchResult:
    version: str = ""
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    exit_value: int = 0

class Superbench(Tool):
    @property
    def sb_setup_script(self):
        return "sb_util.sh"

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
        return f"/home/{self.node.tools[Whoami].get_username()}/superbench_{self.date_tag}"

    @property
    def sb_image_tag(self) -> str:
        return f"superbench/superbench:{self._sb_image_tag}"

    @property
    def home_dir(self) -> str:
        return f"/home/{self.node.tools[Whoami].get_username()}"

    @property
    def sb_exec_timeout(self) -> int:
        return 3600
    
    @property
    def sb_config(self) -> str:
        if not self._sb_config:
            # Template substitute superbench config, for now only "NUM_GPU" is relevant
            sb_config_tpt = PurePath(__file__).parent.joinpath("configs", self._sb_config_tpt)
            sb_cfg = open(sb_config_tpt).read()

            gpu_count = self.node.tools[NvidiaSmi].get_gpu_count()
            sb_cfg = sb_cfg.format(NUM_GPU=gpu_count)

            sb_cfg_tempdir = self.working_dir
            sb_cfg_temp = PosixPath(sb_cfg_tempdir, self._sb_config_tpt)
            with open(sb_cfg_temp, "w") as cfg_file:
                cfg_file.write(sb_cfg)
            self._sb_config = sb_cfg_temp
        return self._sb_config

    @property
    def sb_branch(self) -> str:
        return self._sb_branch

    def __init__(self, node: Node, *args: Any, **kwargs: Any) -> None:
        super().__init__(node, args, kwargs)
        self._sb_repo = kwargs["sb_repo"]
        self._sb_branch = kwargs["sb_branch"]
        self._sb_config_tpt = kwargs["sb_config"]
        self._sb_image_tag = kwargs["sb_image_tag"]
        self._sb_config = ""

        # This is the date-time value which superbench dir will be suffixed with
        date_format = "%Y-%m-%d_%H-%M-%S"
        self.date_tag = datetime.now().strftime(date_format)

        # This will be populated while parsing result tgz
        self.node_list = []
        self.working_dir = tempfile.mkdtemp()
        
        print(f"_sb_repo:{self._sb_repo},\n_sb_branch:{self._sb_branch},\n_sb_config_tpt:{self._sb_config_tpt},\n_sb_image_tag:{self._sb_image_tag},\n_sb_config:{self._sb_config},\ndate_tag:{self.date_tag}")

    def run_test(
        self,
        test_result: TestResult,
        log_path,
        sb_run_timeout: int = 1800,
    ) -> List[SuperbenchResult]:

        # run superbench tests
        sb_cfg_filename = os.path.basename(self.sb_config)
        self.node.execute(f"{self.home_dir}/{self.sb_setup_script} "
                          f"--action run "
                          f"--sb-config-file {sb_cfg_filename} "
                          f"--sb-repo-dir {self.sb_install_path} ",
                          cwd=self.home_dir, expected_exit_code=0,
                          timeout=sb_run_timeout)

        # tar gzip result directory and copy to local machine
        sb_local_result_tgz = PosixPath(log_path, "outputs.tgz")
        self.node.shell.copy_back(PosixPath(self.sb_install_path, "outputs.tgz"),
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
            if key == "node":
                self.node_list.append(value)
            else:
                test_name, subtext = key.split("/", 1)
                if not test_name in test_results:
                    test_results[test_name] = {}
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
        """
        Expand result tgz:
        outputs
               /sb_run
                     /sb.config.yaml
                     /results-summary.jsonl
               /node_info
                     /sys_info.json
        """
        result_tmpdir = self.working_dir
        print(f"Superbench result temp dir: {result_tmpdir}")
        subprocess.run(["tar", "zxf", sb_result_tgz],
                       check=True, cwd=result_tmpdir)

        cfg_yaml = PosixPath(result_tmpdir, "outputs/sb_run/sb.config.yaml")
        result_json = PosixPath(result_tmpdir, "outputs/sb_run/results-summary.jsonl")

        enabled_tests = self.get_enabled_tests(cfg_yaml)
        result_groups = self.group_result_by_test(result_json, enabled_tests)

        return self.split_result(result_groups)

    def _install(self) -> bool:
        assert isinstance(self.node.os, Posix), f"{self.node.os} is not supported"

        # Install host packages, superbench container is self contained
        self.node.os.install_packages(["lshw", "rsync", "bzip2-devel", "inih",
                                       "xfsprogs", "pigz", "parted", "golang",
                                       "dosfstools", "cdrkit", "build-essential", "acl"])

        # Copy over superbench config and setup script to the node
        copy_to_remote = self.node.tools[RemoteCopy].copy_to_remote
        copy_to_remote(self.sb_config,
                       PurePath(self.home_dir))

        copy_to_remote(PurePath(__file__).parent.joinpath(self.sb_setup_script),
                       PurePath(self.home_dir))
        self.node.tools[Chmod].chmod(PurePath(self.home_dir).joinpath(self.sb_setup_script), "a+rx")

        self.node.execute(f"{self.home_dir}/{self.sb_setup_script} "
                          f"--action install "
                          f"--sb-repo-dir {self.sb_install_path} "
                          f"--sb-image-tag {self.sb_image_tag} ",
                          cwd=self.home_dir, expected_exit_code=0,
                          timeout=self.sb_exec_timeout)

        return self._check_exists()

    def _check_exists(self) -> bool:
        result = self.node.execute(f"{self.home_dir}/{self.sb_setup_script} "
                                   f"--action verify "
                                   f"--sb-repo-dir {self.sb_install_path} ",
                                   timeout=30)
        if result.exit_code != 0:
            print(f"superbench is not installed:\nstdout: {result.stdout}")
            return False
        else:
            return True
