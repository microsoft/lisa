# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
from pathlib import Path, PurePath
from typing import Any, Dict

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import Cp, Free, Ls, Lscpu, QemuImg, Rm, Ssh, Usermod, Wget
from lisa.util import SkippedException
from microsoft.testsuites.mshv.cloud_hypervisor_tool import CloudHypervisor


@TestSuiteMetadata(
    area="mshv",
    category="stress",
    description="""
    This test suite contains tests that are meant to be run on the
    Microsoft Hypervisor (MSHV) root partition.
    """,
)
class MshvHostStressTestSuite(TestSuite):
    IGVM_PATH_VARIABLE = "igvm_path"
    CONFIG_VARIABLE = "mshv_vm_create_stress_configs"
    DEFAULT_ITERS = 15
    DEFAULT_CPUS_PER_VM = 1
    DEFAULT_MEM_PER_VM_MB = 1024
    DEFAULT_GUEST_VM_TYPE = "NON-CVM"

    HYPERVISOR_FW_NAME = "hypervisor-fw"
    DISK_IMG_NAME = "vm_disk_img.raw"

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not node.tools[Ls].path_exists("/dev/mshv", sudo=True):
            raise SkippedException("This suite is for MSHV root partition only")

        # add user to mshv group for access to /dev/mshv
        node.tools[Usermod].add_user_to_group("mshv", sudo=True)

        working_path = node.get_working_path()
        node.tools[Wget].get(
            "https://github.com/cloud-hypervisor/rust-hypervisor-firmware/releases/download/0.4.1/hypervisor-fw",  # noqa: E501
            file_path=str(working_path),
            filename=self.HYPERVISOR_FW_NAME,
        )
        node.tools[Wget].get(
            "https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img",  # noqa: E501
            file_path=str(working_path),
            filename=f"{self.DISK_IMG_NAME}.img",
            timeout=1200,
        )
        node.tools[QemuImg].convert(
            "qcow2",
            str(working_path / f"{self.DISK_IMG_NAME}.img"),
            "raw",
            str(working_path / self.DISK_IMG_NAME),
        )

    @TestCaseMetadata(
        description="""
        Stress the MSHV virt stack by repeatedly creating and destroying
        multiple VMs in parallel. By default creates VMs with 1 vCPU and
        1 GiB of RAM each. Number of VMs createdis equal to the number of
        CPUs available on the host. By default, the test is repeated 25
        times. All of these can be configured via the variable
        "mshv_vm_create_stress_configs" in the runbook.
        """,
        priority=4,
        timeout=10800,  # 3 hours
    )
    def stress_mshv_vm_create(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
        log_path: Path,
        result: TestResult,
    ) -> None:
        configs = variables.get(self.CONFIG_VARIABLE, [{}])
        igvm_path = variables.get(self.IGVM_PATH_VARIABLE, "")
        guest_vm_type = variables.get("clh_guest_vm_type", self.DEFAULT_GUEST_VM_TYPE)

        # This test can end up creating and a lot of ssh sessions and these kept active
        # at the same time.
        # In Ubuntu, the default limit is easily exceeded. So change the MaxSessions
        # property in sshd_config to a high number that is unlikely to be exceeded.
        node.tools[Ssh].set_max_session()

        failures = 0
        for config in configs:
            times = config.get("iterations", self.DEFAULT_ITERS)
            cpus_per_vm = config.get("cpus_per_vm", self.DEFAULT_CPUS_PER_VM)
            mem_per_vm_mb = config.get("mem_per_vm_mb", self.DEFAULT_MEM_PER_VM_MB)
            test_name = f"mshv_stress_vm_create_{times}times_{cpus_per_vm}cpu_{mem_per_vm_mb}MB"  # noqa: E501
            try:
                self._mshv_stress_vm_create(
                    times=times,
                    cpus_per_vm=cpus_per_vm,
                    mem_per_vm_mb=mem_per_vm_mb,
                    log=log,
                    node=node,
                    log_path=log_path,
                    guest_vm_type=guest_vm_type,
                    igvm_path=igvm_path,
                )
                send_sub_test_result_message(
                    test_result=result,
                    test_case_name=test_name,
                    test_status=TestStatus.PASSED,
                )
            except Exception as e:
                failures += 1
                log.error(f"{test_name} FAILED: {e}")
                send_sub_test_result_message(
                    test_result=result,
                    test_case_name=test_name,
                    test_status=TestStatus.FAILED,
                    test_message=repr(e),
                )
        node.tools[CloudHypervisor].save_dmesg_logs(node, log_path)
        assert_that(failures).is_equal_to(0)
        return

    def _mshv_stress_vm_create(
        self,
        times: int,
        cpus_per_vm: int,
        mem_per_vm_mb: int,
        log: Logger,
        node: Node,
        log_path: Path,
        guest_vm_type: str = "NON-CVM",
        igvm_path: str = "",
    ) -> None:
        log.info(
            f"MSHV stress VM create: times={times}, cpus_per_vm={cpus_per_vm}, mem_per_vm_mb={mem_per_vm_mb}"  # noqa: E501
        )
        hypervisor_fw_path = str(node.get_working_path() / self.HYPERVISOR_FW_NAME)
        disk_img_path = node.get_working_path() / self.DISK_IMG_NAME
        disk_img_copy_path = self._get_disk_img_copy_path(node)
        threads = node.tools[Lscpu].get_thread_count()
        vm_count = int(threads / cpus_per_vm)
        failures = 0
        for test_iter in range(times):
            log.info(f"Test iteration {test_iter + 1} of {times}")
            node.tools[Free].log_memory_stats_mb()
            procs = []
            for i in range(vm_count):
                vm_disk_img_path = disk_img_copy_path / f"VM{i}_{self.DISK_IMG_NAME}"
                vm_log_file_path = disk_img_copy_path / f"CH_VM{i}.log"
                is_os_disk_present = node.tools[Ls].path_exists(str(vm_disk_img_path))
                if not is_os_disk_present:
                    node.tools[Cp].copy(
                        disk_img_path,
                        vm_disk_img_path,
                        sudo=True,
                        timeout=1200,
                    )
                log.info(f"Starting VM {i}")
                p = node.tools[CloudHypervisor].start_vm_async(
                    kernel=hypervisor_fw_path,
                    cpus=cpus_per_vm,
                    memory_mb=mem_per_vm_mb,
                    disk_path=str(vm_disk_img_path),
                    sudo=True,
                    guest_vm_type=guest_vm_type,
                    igvm_path=igvm_path,
                    log_file=str(vm_log_file_path),
                )
                if not p:
                    node.shell.copy_back(
                        vm_log_file_path,
                        log_path / vm_log_file_path,
                    )
                assert_that(p).described_as(f"Failed to create VM {i}").is_not_none()
                procs.append(p)
                node.tools[Free].log_memory_stats_mb()
                assert_that(p.is_running()).described_as(
                    f"VM {i} failed to start"
                ).is_true()

            # keep the VMs running for a while
            sleep_time = 10
            if guest_vm_type == "CVM":
                # CVM guest take little more time to boot
                # 20 seconds per VM (with default 1024M)
                sleep_time = 20 * vm_count
            time.sleep(sleep_time)

            for i in range(len(procs)):
                p = procs[i]
                if not p.is_running():
                    log.info(f"VM {i} was not running")
                    failures += 1
                    continue
                log.info(f"Killing VM {i}")
                p.kill()

            if guest_vm_type == "CVM":
                # CVM guest killing takes sometime
                sleep_time = 20
                time.sleep(sleep_time)

            node.tools[Free].log_memory_stats_mb()

        for i in range(vm_count):
            disk_img_file = disk_img_copy_path / f"VM{i}_{self.DISK_IMG_NAME}"
            node.tools[Rm].remove_file(str(disk_img_file), sudo=True)
            vm_log_file = disk_img_copy_path / f"CH_VM{i}.log"
            node.tools[Rm].remove_file(str(vm_log_file), sudo=True)

        assert_that(failures).is_equal_to(0)

    def _get_disk_img_copy_path(self, node: Node) -> PurePath:
        # Azure temporary disk is mounted at /mnt. It has more space then OS
        # disk. Use it for storing copies of the disk image if it exists.
        if node.tools[Ls].path_exists("/mnt"):
            return PurePath("/mnt")
        else:
            return node.working_path
