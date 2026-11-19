# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional

from assertpy import assert_that
from microsoft.testsuites.mshv.cloud_hypervisor_tool import CloudHypervisor
from paramiko.ssh_exception import SSHException

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import (
    Cp,
    Free,
    Ls,
    Lsblk,
    Lscpu,
    Mount,
    QemuImg,
    Rm,
    Ssh,
    Usermod,
    Wget,
)
from lisa.tools.lsblk import DiskInfo
from lisa.tools.mkfs import FileSystem
from lisa.util import LisaException, SkippedException
from lisa.util.process import ExecutableResult, Process


class MshvGuestCleanupError(LisaException):
    pass


@TestSuiteMetadata(
    area="mshv",
    category="stress",
    description="""
    This test suite contains tests that are meant to be run on the
    Microsoft Hypervisor (MSHV) root partition.
    """,
    requirement=simple_requirement(supported_host_capabilities=["mshv"]),
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
        Guest failures retain process output and VMM logs. Each iteration
        stops its guests even on failure; uncertain cleanup aborts further
        configurations rather than reusing the host.
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
        for config_index, config in enumerate(configs):
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
                    config_index=config_index,
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
                if isinstance(e, MshvGuestCleanupError):
                    node.mark_dirty()
                    cleanup_tool: CloudHypervisor = node.tools[CloudHypervisor]
                    cleanup_tool.save_dmesg_logs(node, log_path)
                    raise
        ch_tool: CloudHypervisor = node.tools[CloudHypervisor]
        ch_tool.save_dmesg_logs(node, log_path)
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
        config_index: int,
        guest_vm_type: str = "NON-CVM",
        igvm_path: str = "",
    ) -> None:
        log.info(
            f"MSHV stress VM create: times={times}, cpus_per_vm={cpus_per_vm}, mem_per_vm_mb={mem_per_vm_mb}"  # noqa: E501
        )
        hypervisor_fw_path = str(node.get_working_path() / self.HYPERVISOR_FW_NAME)
        disk_img_path = node.get_working_path() / self.DISK_IMG_NAME
        disk_img_copy_path = self._get_disk_img_copy_path(node, log)
        threads = node.tools[Lscpu].get_thread_count()
        vm_count = int(threads / cpus_per_vm)
        failures = 0
        for test_iter in range(times):
            log.info(f"Test iteration {test_iter + 1} of {times}")
            failure_log_path = log_path / (
                f"config-{config_index + 1}_cpu-{cpus_per_vm}_"
                f"memory-{mem_per_vm_mb}_iteration-{test_iter + 1}"
            )
            node.tools[Free].log_memory_stats_mb()
            procs: List[Process] = []
            try:
                for i in range(vm_count):
                    vm_disk_img_path = (
                        disk_img_copy_path / f"VM{i}_{self.DISK_IMG_NAME}"
                    )
                    vm_log_file_path = disk_img_copy_path / f"CH_VM{i}.log"
                    is_os_disk_present = node.tools[Ls].path_exists(
                        str(vm_disk_img_path)
                    )
                    if not is_os_disk_present:
                        node.tools[Cp].copy(
                            disk_img_path,
                            vm_disk_img_path,
                            sudo=True,
                            timeout=1200,
                        )
                    log.info(f"Starting VM {i}")
                    ch_tool: CloudHypervisor = node.tools[CloudHypervisor]
                    p = ch_tool.start_vm_async(
                        kernel=hypervisor_fw_path,
                        cpus=cpus_per_vm,
                        memory_mb=mem_per_vm_mb,
                        disk_path=str(vm_disk_img_path),
                        sudo=True,
                        guest_vm_type=guest_vm_type,
                        igvm_path=igvm_path,
                        log_file=str(vm_log_file_path),
                    )
                    procs.append(p)
                    node.tools[Free].log_memory_stats_mb()
                    if not p.is_running():
                        process_result = p.wait_result(timeout=30)
                        self._save_vm_failure_logs(
                            node,
                            log,
                            failure_log_path,
                            vm_log_file_path,
                            process_result,
                        )
                        raise LisaException(
                            f"VM {i} failed to start (exit code "
                            f"{process_result.exit_code}). stdout: "
                            f"{process_result.stdout}\nstderr: {process_result.stderr}"
                        )

                # Keep the VMs running for a while.
                sleep_time = 10
                if guest_vm_type == "CVM":
                    sleep_time = 20 * vm_count
                time.sleep(sleep_time)

                for i, p in enumerate(procs):
                    if not p.is_running():
                        failures += 1
                        self._save_vm_failure_logs(
                            node,
                            log,
                            failure_log_path,
                            disk_img_copy_path / f"CH_VM{i}.log",
                            p.wait_result(timeout=30),
                        )
            finally:
                self._stop_guest_processes(procs, log)

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

    def _stop_guest_processes(self, procs: List[Process], log: Logger) -> None:
        errors: List[str] = []
        for i, process in enumerate(procs):
            try:
                if process.is_running():
                    log.info(f"Killing VM {i}")
                    process.kill()
                process.wait_result(timeout=30)
                if process.is_running():
                    raise LisaException(f"VM {i} is still running after cleanup")
            except (LisaException, SSHException, OSError) as error:
                log.exception(f"Failed to clean up VM {i}")
                errors.append(f"VM {i}: {error}")
        if errors:
            raise MshvGuestCleanupError(
                f"Guest cleanup failed; stopping further configurations: "
                f"{'; '.join(errors)}"
            )

    def _save_vm_failure_logs(
        self,
        node: Node,
        log: Logger,
        log_path: Path,
        vm_log_file_path: PurePath,
        process_result: ExecutableResult,
    ) -> None:
        output = (
            f"exit code: {process_result.exit_code}\n"
            f"stdout:\n{process_result.stdout}\nstderr:\n{process_result.stderr}"
        )
        log.error(f"Guest process failed: {output}")
        log_path.mkdir(parents=True, exist_ok=True)
        (log_path / f"{vm_log_file_path.stem}.console.log").write_text(
            output, encoding="utf-8"
        )
        try:
            node.shell.copy_back(vm_log_file_path, log_path / vm_log_file_path.name)
        except (LisaException, SSHException, OSError) as error:
            log.warning(f"Failed to collect {vm_log_file_path}: {error}")

    def _get_disk_img_copy_path(self, node: Node, log: Logger) -> PurePath:
        # The guest disk image is copied once per concurrent VM, so we need
        # a directory backed by a large disk. Prefer an existing resource
        # disk mount; otherwise try to mount an unused nvme*n1 disk at
        # /mnt/resource.
        mount_point = "/mnt/resource"
        fallback_mount = "/mnt"

        disks = node.tools[Lsblk].get_disks(force_run=True)

        if self._is_mountpoint_in_use(disks, mount_point):
            return PurePath(mount_point)
        if self._is_mountpoint_in_use(disks, fallback_mount):
            return PurePath(fallback_mount)

        candidate = self._find_unused_nvme_disk(disks)
        if candidate is None:
            log.info(
                "No mounted resource disk and no unused nvme*n1 disk found; "
                "falling back to working path. The test may run out of disk "
                "space."
            )
            return node.working_path

        try:
            node.execute(f"mkdir -p {mount_point}", shell=True, sudo=True)
            node.tools[Mount].mount(
                name=candidate,
                point=mount_point,
                fs_type=FileSystem.ext4,
                format_=True,
            )
        except Exception as e:
            log.info(
                f"Failed to mount {candidate} at {mount_point}: {e}; "
                "falling back to working path."
            )
            return node.working_path

        log.info(f"Mounted {candidate} at {mount_point} for VM disk copies")
        return PurePath(mount_point)

    @staticmethod
    def _is_mountpoint_in_use(disks: List[DiskInfo], mountpoint: str) -> bool:
        for disk in disks:
            if disk.mountpoint == mountpoint:
                return True
            for partition in disk.partitions:
                if partition.mountpoint == mountpoint:
                    return True
        return False

    def _find_unused_nvme_disk(self, disks: List[DiskInfo]) -> Optional[str]:
        nvme_pattern = re.compile(r"^nvme\d+n1$")
        for disk in disks:
            if disk.is_os_disk:
                continue
            if not nvme_pattern.match(disk.name):
                continue
            if disk.partitions:
                continue
            if disk.is_mounted:
                continue
            return f"/dev/{disk.name}"
        return None
