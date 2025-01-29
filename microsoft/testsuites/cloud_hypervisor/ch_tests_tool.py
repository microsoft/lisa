# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Set, Type

from assertpy.assertpy import assert_that, fail

from lisa import Node
from lisa.executable import Tool
from lisa.features import SerialConsole
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import (
    Cat,
    Chmod,
    Chown,
    Dmesg,
    Docker,
    Echo,
    Git,
    Ls,
    Mkdir,
    Modprobe,
    Sed,
    Whoami,
)
from lisa.util import UnsupportedDistroException, find_groups_in_lines


@dataclass
class CloudHypervisorTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    message: str = ""


class CloudHypervisorTests(Tool):
    CMD_TIME_OUT = 3600
    # Slightly higher case timeout to give the case a window to
    # - list subtests before running the tests.
    # - extract sub test results from stdout and report them.
    CASE_TIME_OUT = CMD_TIME_OUT + 1200
    # 2 Hrs of timeout for perf tests and 2400 seconds for other operations
    PERF_CASE_TIME_OUT = 7200 + 2400
    PERF_CMD_TIME_OUT = 1200

    upstream_repo = "https://github.com/cloud-hypervisor/cloud-hypervisor.git"
    env_vars = {
        "RUST_BACKTRACE": "full",
    }

    ms_clh_repo = ""
    use_ms_clh_repo = False
    ms_access_token = ""
    clh_guest_vm_type = ""
    use_ms_guest_kernel = ""
    use_ms_hypervisor_fw = ""
    use_ms_ovmf_fw = ""
    use_ms_bz_image = ""

    # Block perf related env var
    use_datadisk = ""
    disable_datadisk_cache = ""
    block_size_kb = ""

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
        test_type: str,
        hypervisor: str,
        log_path: Path,
        ref: str = "",
        only: Optional[List[str]] = None,
        skip: Optional[List[str]] = None,
    ) -> None:
        if ref:
            self.node.tools[Git].checkout(ref, self.repo_root)

        subtests = self._list_subtests(hypervisor, test_type)

        if only is not None:
            if not skip:
                skip = []
            # Add everything except 'only' to skip list
            skip += list(subtests.difference(only))
        if skip is not None:
            subtests.difference_update(skip)
            skip_args = " ".join(map(lambda t: f"--skip {t}", skip))
        else:
            skip_args = ""
        self._log.debug(f"Final Subtests list to run: {subtests}")

        if isinstance(self.node.os, CBLMariner) and hypervisor == "mshv":
            # Install dependency to create VDPA Devices
            self.node.os.install_packages(["iproute", "iproute-devel"])
            # Load VDPA kernel module and create devices
            self._configure_vdpa_devices(self.node)

        result = self.run(
            f"tests --hypervisor {hypervisor} --{test_type} -- -- {skip_args}",
            timeout=self.CMD_TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,  # print out result of each test
            shell=True,
            update_envs=self.env_vars,
        )

        # Report subtest results and collect logs before doing any
        # assertions.
        results = self._extract_test_results(result.stdout, log_path, subtests)
        failures = [r.name for r in results if r.status == TestStatus.FAILED]

        for r in results:
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=r.name,
                test_status=r.status,
                test_message=r.message,
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
        hypervisor: str,
        log_path: Path,
        ref: str = "",
        only: Optional[List[str]] = None,
        skip: Optional[List[str]] = None,
        subtest_timeout: Optional[int] = None,
    ) -> None:
        if self.use_datadisk:
            self._set_data_disk()
            self._save_kernel_logs(log_path)

        if ref:
            self.node.tools[Git].checkout(ref, self.repo_root)

        subtests = self._list_perf_metrics_tests(hypervisor=hypervisor)
        failed_testcases = []

        if only is not None:
            if not skip:
                skip = []
            # Add everything except 'only' to skip list
            skip += list(subtests.difference(only))
        if skip is not None:
            subtests.difference_update(skip)

        self._log.debug(f"Final Subtests list to run: {subtests}")

        for testcase in subtests:
            testcase_log_file = log_path.joinpath(f"{testcase}.log")

            status: TestStatus = TestStatus.QUEUED
            metrics: str = ""
            trace: str = ""
            cmd_args: str = (
                f"tests --hypervisor {hypervisor} --metrics -- --"
                f" --test-filter {testcase}"
            )
            if subtest_timeout:
                cmd_args = f"{cmd_args} --timeout {subtest_timeout}"
            try:
                cmd_timeout = self.PERF_CMD_TIME_OUT
                if self.clh_guest_vm_type == "CVM":
                    cmd_timeout = cmd_timeout + 300
                result = self.run(
                    cmd_args,
                    timeout=cmd_timeout,
                    force_run=True,
                    cwd=self.repo_root,
                    no_info_log=False,  # print out result of each test
                    shell=True,
                    update_envs=self.env_vars,
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
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=testcase,
                test_status=status,
                test_message=msg,
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
        clone_path = self.get_tool_path(use_global=True)
        if self.use_ms_clh_repo:
            git.clone(
                self.ms_clh_repo,
                clone_path,
                auth_token=self.ms_access_token,
            )
            self.env_vars["GUEST_VM_TYPE"] = self.clh_guest_vm_type
            if self.use_ms_guest_kernel:
                self.env_vars["USE_MS_GUEST_KERNEL"] = self.use_ms_guest_kernel
            if self.use_ms_hypervisor_fw:
                self.env_vars["USE_MS_HV_FW"] = self.use_ms_hypervisor_fw
            if self.use_ms_ovmf_fw:
                self.env_vars["USE_MS_OVMF_FW"] = self.use_ms_ovmf_fw
            if self.use_ms_bz_image:
                self.env_vars["USE_MS_BZ_IMAGE"] = self.use_ms_bz_image

            if self.use_datadisk:
                self.env_vars["USE_DATADISK"] = self.use_datadisk
            if self.disable_datadisk_cache:
                self.env_vars["DISABLE_DATADISK_CACHING"] = self.disable_datadisk_cache
            if self.block_size_kb:
                self.env_vars["PERF_BLOCK_SIZE_KB"] = self.block_size_kb
        else:
            git.clone(self.upstream_repo, clone_path)

        if isinstance(self.node.os, CBLMariner):
            docker_config_dir = "/etc/docker/"

            docker_config: Dict[str, Any] = {}
            docker_config["default-ulimits"] = {}
            nofiles = {"Hard": 65535, "Name": "nofile", "Soft": 65535}
            docker_config["default-ulimits"]["nofile"] = nofiles

            ls = self.node.tools[Ls]
            if not ls.path_exists(path=docker_config_dir, sudo=True):
                self.node.tools[Mkdir].create_directory(
                    path=docker_config_dir,
                    sudo=True,
                )

            node_info = self.node.get_information()
            distro = node_info.get("distro_version", "")
            if distro == "Microsoft Azure Linux 3.0":
                docker_config["userland-proxy"] = False

            daemon_json = json.dumps(docker_config).replace('"', '\\"')
            daemon_json_file = PurePath(f"{docker_config_dir}/daemon.json")
            self.node.tools[Echo].write_to_file(
                daemon_json, daemon_json_file, sudo=True
            )

        self.node.execute("groupadd -f docker", expected_exit_code=0)
        username = self.node.tools[Whoami].get_username()
        res = self.node.execute("getent group docker", expected_exit_code=0)
        if username not in res.stdout:  # if current user is not in docker group
            self.node.execute(f"usermod -a -G docker {username}", sudo=True)
            # reboot for group membership change to take effect
            self.node.reboot(time_out=900)

        self.node.tools[Docker].start()

        return self._check_exists()

    def _list_subtests(self, hypervisor: str, test_type: str) -> Set[str]:
        result = self.run(
            f"tests --hypervisor {hypervisor} --{test_type} -- -- --list",
            timeout=self.CMD_TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,
            shell=True,
            update_envs=self.env_vars,
        )
        # e.g. "integration::test_vfio: test"
        matches = re.findall(r"^(.*::.*): test", result.stdout, re.M)
        self._log.debug(f"Subtests list: {matches}")
        return set(matches)

    def _extract_test_results(
        self, output: str, log_path: Path, subtests: Set[str]
    ) -> List[CloudHypervisorTestResult]:
        results: List[CloudHypervisorTestResult] = []
        subtest_status: Dict[str, TestStatus] = {t: TestStatus.QUEUED for t in subtests}

        # Example output:
        # test common_parallel::test_snapshot_restore_basic ... ok
        # test common_parallel::test_virtio_balloon_deflate_on_oom ... FAILED

        pattern = re.compile(r"test (?P<test_name>[^\s]+) \.{3} (?P<status>\w+)")
        test_results = find_groups_in_lines(
            lines=output,
            pattern=pattern,
        )

        for test_result in test_results:
            test_status = test_result["status"].strip().lower()
            test_name = test_result["test_name"].strip().lower()

            if test_status == "started":
                status = TestStatus.RUNNING
            elif test_status == "ok":
                status = TestStatus.PASSED
            elif test_status == "failed":
                status = TestStatus.FAILED
            elif test_status == "ignored":
                status = TestStatus.SKIPPED

            subtest_status[test_name] = status

        messages = {
            TestStatus.QUEUED: "Subtest did not start",
            TestStatus.RUNNING: "Subtest failed to finish - timed out",
        }
        for subtest in subtests:
            status = subtest_status[subtest]
            message = messages.get(status, "")

            if status == TestStatus.RUNNING:
                # Sub-test started running but didn't finish within the stipulated time.
                # It should be treated as a failure.
                status = TestStatus.FAILED

            results.append(
                CloudHypervisorTestResult(
                    name=subtest,
                    status=status,
                    message=message,
                )
            )

        return results

    def _list_perf_metrics_tests(self, hypervisor: str = "kvm") -> Set[str]:
        tests_list = []
        result = self.run(
            f"tests --hypervisor {hypervisor} --metrics -- -- --list-tests",
            timeout=self.PERF_CMD_TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            shell=True,
            expected_exit_code=0,
            update_envs=self.env_vars,
        )

        stdout = result.stdout

        # Ex. String for below regex
        # "boot_time_ms" (test_timeout=2s,test_iterations=10)
        # "virtio_net_throughput_single_queue_rx_gbps" (test_timeout = 10s, test_iterations = 5, num_queues = 2, queue_size = 256, rx = true, bandwidth = true) # noqa: E501
        # "block_multi_queue_random_write_IOPS" (test_timeout = 10s, test_iterations = 5, num_queues = 2, queue_size = 128, fio_ops = randwrite, bandwidth = false) # noqa: E501
        # "block_multi_queue_random_read_IOPS" (test_timeout = 10s, test_iterations = 5, num_queues = 2, queue_size = 128, fio_ops = randread, bandwidth = false) # noqa: E501

        regex = '\\"(.*)\\"(.*)test_timeout(.*), test_iterations(.*)\\)'

        pattern = re.compile(regex)
        tests_list = [match[0] for match in pattern.findall(stdout)]

        self._log.debug(f"Testcases found: {tests_list}")
        return set(tests_list)

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
            with open(str(dmesg_path), "w", encoding="utf-8") as f:
                f.write(dmesg_str)

    def _configure_vdpa_devices(self, node: Node) -> None:
        # Load the VDPA kernel modules
        node.tools[Modprobe].load("vdpa")
        node.tools[Modprobe].load("vhost_vdpa")
        node.tools[Modprobe].load("vdpa_sim")
        node.tools[Modprobe].load("vdpa_sim_blk")
        node.tools[Modprobe].load("vdpa_sim_net")

        # Device Config
        device_config = [
            {
                "dev_name": "vdpa-blk0",
                "mgmtdev_name": "vdpasim_blk",
                "device_path": "/dev/vhost-vdpa-0",
                "permission": "660",
            },
            {
                "dev_name": "vdpa-blk1",
                "mgmtdev_name": "vdpasim_blk",
                "device_path": "/dev/vhost-vdpa-1",
                "permission": "660",
            },
            {
                "dev_name": "vdpa-blk2",
                "mgmtdev_name": "vdpasim_net",
                "device_path": "/dev/vhost-vdpa-2",
                "permission": "660",
            },
        ]

        # Create VDPA Devices
        user = node.tools[Whoami].get_username()
        for device in device_config:
            dev_name = device["dev_name"]
            mgmtdev_name = device["mgmtdev_name"]
            device_path = device["device_path"]
            permission = device["permission"]

            node.execute(
                cmd=f"vdpa dev add name {dev_name} mgmtdev {mgmtdev_name}",
                sudo=True,
                shell=True,
            )
            node.tools[Chown].change_owner(file=PurePath(device_path), user=user)
            node.tools[Chmod].chmod(path=device_path, permission=permission, sudo=True)

    def _set_data_disk(self) -> None:
        # datadisk_name = ""
        # lsblk = self.node.tools[Lsblk]
        # disks = lsblk.get_disks()
        # # get the first unmounted disk (data disk)
        # for disk in disks:
        #     if disk.is_mounted:
        #         continue
        #     if disk.name.startswith("sd"):
        #         datadisk_name = disk.device_name
        #         break
        # # running lsblk once again, just for human readable logs
        # lsblk.run()
        # if not datadisk_name:
        #     raise LisaException("No unmounted data disk (/dev/sdX) found")

        """
        Following is the last usable entry in e829 table and is safest to use for
        pmem since its most likely to be free. 0x0000001000000000 is64G.
        [    0.000000] BIOS-e820: [mem 0x0000001000000000-0x00000040ffffffff] usable

        """
        memmap_str = "memmap=16G!64G"

        self._log.debug("lsblk before reboot")
        self.node.execute("lsblk", shell=True, sudo=True)

        sed = self.node.tools[Sed]
        cat = self.node.tools[Cat]
        grub_file = "/etc/default/grub"
        grub_cmdline = cat.read_with_filter(
            file=grub_file,
            grep_string="GRUB_CMDLINE_LINUX=",
            sudo=True,
        )
        if memmap_str not in grub_cmdline:
            sed.substitute(
                file=grub_file,
                match_lines="^GRUB_CMDLINE_LINUX=",
                regexp='"$',
                replacement=' memmap=16G!64G "',
                sudo=True,
            )
        if isinstance(self.node.os, CBLMariner):
            self.node.execute("grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True)
        elif isinstance(self.node.os, Ubuntu):
            self.node.execute("update-grub", sudo=True)
        else:
            raise UnsupportedDistroException(
                self.node.os,
                "pmem for CH tests is supported only on Ubuntu and CBLMariner",
            )

        self.node.reboot(time_out=900)
        self.node.execute("lsblk", shell=True, sudo=True)
        self.node.execute("ls /dev/pmem*", shell=True, sudo=True)

        datadisk_name = "/dev/pmem0"
        self._log.debug(f"Using data disk: {datadisk_name}")
        self.env_vars["DATADISK_NAME"] = datadisk_name


def extract_jsons(input_string: str) -> List[Any]:
    json_results: List[Any] = []
    start_index = input_string.find("{")
    search_index = start_index
    while start_index != -1:
        end_index = input_string.find("}", search_index) + 1
        if end_index == 0:
            start_index = input_string.find("{", start_index + 1)
            search_index = start_index
            continue
        json_string = input_string[start_index:end_index]
        try:
            result = json.loads(json_string)
            json_results.append(result)
            start_index = input_string.find("{", end_index)
            search_index = start_index
        except json.decoder.JSONDecodeError:
            search_index = end_index
    return json_results
