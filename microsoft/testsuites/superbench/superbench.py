# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import itertools
import json
import os
import subprocess
import tempfile
import io
import csv
import re

from dataclasses import dataclass
from pathlib import Path, PurePath, PosixPath
from typing import Any, Dict, List, Tuple, Type
from datetime import datetime

from assertpy import assert_that
import yaml

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

# curl --header 'Metadata: true' "http://169.254.169.254/metadata/instance?api-version=2021-01-01" | jq > sku.metadata.json

class DashBoard:
    __slots__ = ("Team",
                 "RunTimestamp",
                 "SessionType",
                 "HostMinroot",
                 "HostOSVersion",
                 "HostMemoryPartition",
                 "Hardware",
                 "VMType",
                 "VMOSVersion",
                 "L2Type",
                 "L2OS",
                 "VMSKU",
                 "ContainerCPU",
                 "ContainerMemory",
                 "ContainerConfiguration",
                 "ContainerImage",
                 "StorageConfiguration",
                 "NetworkConfiguration",
                 "GPUSKU",
                 "NumGPUsUsed",
                 "Category",
                 "Workload",
                 "WorkloadParameters",
                 "Benchmark",
                 "TraceDownloadLink",
                 "AdditionalInfo",
                 "cuda",
                 "GPUDriverVersion",
                 "TipSessionId",
                 "Metric",
                 "MetricValue",
                 "Scenario")

    def __init__(self, **kwargs):
        self.assign(**kwargs)

    def assign(self, **kwargs):
        for attr, value in kwargs.items():
            if attr in self.__slots__:
                setattr(self, attr, value)

    def header_csv(self):
        csv_line = io.StringIO()
        writer = csv.writer(csv_line, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(self.__slots__)
        return csv_line.getvalue().replace("AdditionalInfo", "Additional Info")

    def csv(self):
        csv_line = io.StringIO()
        writer = csv.writer(csv_line, quoting=csv.QUOTE_NONNUMERIC)
        values = [getattr(self, attr, "") for attr in self.__slots__]
        writer.writerow(values)
        return csv_line.getvalue()

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

            sb_cfg_temp = PosixPath(self.working_dir, self._sb_config_tpt)
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
        self.variables = kwargs["variables"]

        # This is the date-time value which superbench dir will be suffixed with
        date_format = "%Y-%m-%d_%H-%M-%S"
        self.date_tag = datetime.now().strftime(date_format)

        # This will be populated while parsing result tgz
        self.node_list = []
        self.working_dir = tempfile.mkdtemp(prefix="sb_lisa.")

        print(f"_sb_repo:{self._sb_repo},\n_sb_branch:{self._sb_branch},\n_sb_config_tpt:{self._sb_config_tpt},"
              f"\n_sb_image_tag:{self._sb_image_tag},\n_sb_config:{self._sb_config_tpt},\ndate_tag:{self.date_tag}")

    def dash_board_entry(self, sysinfo, vmSKU):
        nodeinfo = self.node.get_information()

        cuda_version = sysinfo["Accelerator"]["nvidia_info"]["cuda_version"]
        node_info_dict = { "Team" : self.variables["team"],
                           "RunTimestamp" : self.run_timestamp,
                           "VMType" : self.variables["vmtype"],
                           "VMOSVersion" : nodeinfo["distro_version"].replace("Microsoft ", ""),
                           "VMSKU" : vmSKU,
                           "GPUSKU" : sysinfo["Accelerator"]["nvidia_info"]["gpu"][0]["product_name"],
                           "NumGPUsUsed" : sysinfo["Accelerator"]["gpu_count"],
                           "Category" : "GPU Runtime",
                           "Workload" : "Superbench",
                           "AdditionalInfo" : f"{self.variables['image_info']} {cuda_version}",
                           "cuda" : cuda_version,
                           "GPUDriverVersion" : sysinfo["Accelerator"]["nvidia_info"]["driver_version"],
                           "Scenario" : self.variables["scenario"] }
        return DashBoard(**node_info_dict)


    def run_test(
        self,
        test_result: TestResult,
        log_path,
        sb_run_timeout: int = 1800,
    ) -> List[SuperbenchResult]:

        # This is needed for dashboard csv generation
        self.run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

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

        result_list = self.parse_results(sb_local_result_tgz, log_path)
        failed_tests = []
        for result in result_list:
            # create test result message
            info = {"information" : {"version" : result.version,
                                     "exit_value" : result.exit_value}}
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=result.name,
                test_status=result.status,
                other_fields=info,
            )
            # assert that none of the tests failed
            if result.exit_value:
                failed_tests.append(result)

        assert_that(failed_tests, f"The following tests failed: {failed_tests}").is_empty()
        return result_list

    @staticmethod
    def get_enabled_tests(sb_cfg_yaml):
        with open(sb_cfg_yaml, "r") as yaml_file:
            sb_config = yaml.safe_load(yaml_file)

        # Extract entries under superbench.enable
        enabled_tests = sb_config.get("superbench", {}).get("enable", [])

        return enabled_tests

    def notify_result(self, result_json: Dict, tests: list[str],
                      sysinfo: Dict, vmSKU: str, db_csv_file: str) -> Dict[str, Dict[str, int]]:
        """
        For the given superbench result summary:
                - "*return_code" accumulate to test-result object
                - "node" entry extract and store
                - ignore "monitor/gpu*" entries
                - all other entries go into upload csv file
        """
        test_result = {test_name:0 for test_name in tests}

        dashboard: DashBoard = self.dash_board_entry(sysinfo, vmSKU)

        print(f"DashBoard csv file is: {db_csv_file}")
        db_csv_fd = open(db_csv_file, "w")
        db_csv_fd.write(dashboard.header_csv())

        # There is only one node entry now, TODO: handle testing on clusters
        self.node_list.append(result_json.pop("node"))

        for key, value in result_json.items():
            if key.startswith("monitor/gpu"):
                continue

            # Strip gpu number
            test_name = re.sub(":\d+", "", key)

            # If entry is for test return code accumulate the value to check if
            # there were any non-zero return codes.
            if test_name.endswith("/return_code"):
                # In some cases sub-test name has return code
                test_name = test_name.rsplit("/", 1)[0]
                if not test_name in test_result:
                    test_result[test_name] = 0
                test_result[test_name] += int(value)
            else:
                metricvalue = str(round(float(value), 3)) # 3 digit precision
                dashboard.assign(Metric=test_name, MetricValue=metricvalue)
                db_csv_fd.write(dashboard.csv())
        db_csv_fd.close()

        # Build TestResult object list for lisa to process
        result_object_list = []
        for test_name, retval in test_result.items():
            status = TestStatus.FAILED if retval else TestStatus.PASSED
            result_object_list.append(SuperbenchResult(name=test_name,
                                                       status=status, exit_value=retval))

        return result_object_list

    def parse_results(self, sb_result_tgz, log_path):
        """
        Expand result tgz, it has this layout:
        outputs
               /sb_run
                     /sb.config.yaml
                     /results-summary.jsonl
               /node_info
                     /sys_info.json
        """
        subprocess.run(["tar", "zxf", sb_result_tgz],
                       check=True, cwd=self.working_dir)

        cfg_yaml = PosixPath(self.working_dir, "outputs/sb_run/sb.config.yaml")
        result_json_file = PosixPath(self.working_dir, "outputs/sb_run/results-summary.jsonl")
        sysinfo_json_file = PosixPath(self.working_dir, "outputs/node_info/sys_info.json")
        sku_file = PosixPath(self.working_dir, "outputs/node_info/sku.txt")
        db_csv_file = PosixPath(log_path, "dashboard_data.csv")

        sysinfo = json.load(open(sysinfo_json_file))
        vmSKU = open(sku_file).read().strip()
        enabled_tests = self.get_enabled_tests(cfg_yaml)
        return self.notify_result(json.load(open(result_json_file)),
                                  enabled_tests, sysinfo, vmSKU, db_csv_file)

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
