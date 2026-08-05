# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional

from assertpy import assert_that
from microsoft.testsuites.mshv.cloud_hypervisor_tool import CloudHypervisor

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
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
    Uname,
    Usermod,
    Wget,
)
from lisa.tools.lsblk import DiskInfo
from lisa.tools.mkfs import FileSystem
from lisa.util import LisaException, SkippedException
from lisa.util.process import ExecutableResult, Process

# Operational errors raised by remote command execution or file transfer that
# best-effort diagnostics/cleanup should tolerate without masking real
# programming errors. ``AssertionError`` covers LISA's ``expected_exit_code``
# command assertion failures.
_OPERATIONAL_ERRORS = (LisaException, AssertionError, OSError)


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

    # One shared, bounded grace (seconds) after launching the whole VM batch,
    # used to let cloud-hypervisor processes that fail immediately (e.g. a
    # VmCreate failure) exit before the batch is inspected. This grace is taken
    # out of (not added to) the total keep-running duration, so it does not
    # extend the test runtime.
    STARTUP_GRACE_SECONDS = 5
    # Time (seconds) to wait for an already-exited process to yield its result.
    STARTUP_RESULT_TIMEOUT = 30
    # Substrings that, together with a VmCreate error on the same log line,
    # identify an EINVAL returned by the kernel for an unsupported VM
    # configuration.
    _EINVAL_INDICATORS = ("os error 22", "invalid argument", "einval")

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

        passed = 0
        skipped = 0
        failed = 0
        for config_id, config in enumerate(configs):
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
                    config_id=config_id,
                )
                passed += 1
                send_sub_test_result_message(
                    test_result=result,
                    test_case_name=test_name,
                    test_status=TestStatus.PASSED,
                )
            except SkippedException as e:
                # An unsupported host/kernel/MSHV/cloud-hypervisor combination
                # is not a product failure, so report the subtest as skipped.
                skipped += 1
                log.info(f"{test_name} SKIPPED: {e}")
                send_sub_test_result_message(
                    test_result=result,
                    test_case_name=test_name,
                    test_status=TestStatus.SKIPPED,
                    test_message=repr(e),
                )
            except Exception as e:
                failed += 1
                log.error(f"{test_name} FAILED: {e}")
                send_sub_test_result_message(
                    test_result=result,
                    test_case_name=test_name,
                    test_status=TestStatus.FAILED,
                    test_message=repr(e),
                )
        ch_tool: CloudHypervisor = node.tools[CloudHypervisor]
        ch_tool.save_dmesg_logs(node, log_path)

        # Any failing subtest fails the parent. If nothing failed but every
        # configured subtest was skipped for the same unsupported combination,
        # the parent is skipped rather than passed, consistent with LISA
        # conventions. Mixed pass/skip results simply pass.
        assert_that(failed).described_as(
            f"{failed} of {len(configs)} mshv stress subtest(s) failed"
        ).is_equal_to(0)
        if passed == 0 and skipped > 0:
            raise SkippedException(
                "All configured mshv stress subtests were skipped because the "
                "host/kernel/MSHV/cloud-hypervisor combination does not support "
                "creating the requested VM configuration."
            )
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
        config_id: int = 0,
    ) -> None:
        log.info(
            f"MSHV stress VM create: times={times}, cpus_per_vm={cpus_per_vm}, mem_per_vm_mb={mem_per_vm_mb}"  # noqa: E501
        )
        hypervisor_fw_path = str(node.get_working_path() / self.HYPERVISOR_FW_NAME)
        disk_img_path = node.get_working_path() / self.DISK_IMG_NAME
        disk_img_copy_path = self._get_disk_img_copy_path(node, log)
        threads = node.tools[Lscpu].get_thread_count()
        vm_count = int(threads / cpus_per_vm)
        disk_img_files = [
            disk_img_copy_path / f"VM{i}_{self.DISK_IMG_NAME}" for i in range(vm_count)
        ]
        # Track every per-iteration log created so cleanup can preserve and
        # remove all of them. Names are unique per config *and* per iteration
        # (CH_VM{i}_cfg{config_id}_iter{n}.log) so a later iteration, a later
        # config, or the final cleanup can never overwrite earlier evidence.
        created_logs: List[PurePath] = []
        # Count of VMs that die only after the keep-running period across all
        # iterations. These unknown/intermittent failures do not stop the run;
        # the config is failed once, after every iteration has completed.
        pre_stop_failures = 0
        try:
            for test_iter in range(times):
                log.info(f"Test iteration {test_iter + 1} of {times}")
                node.tools[Free].log_memory_stats_mb()
                procs: List[Process] = []
                log_files: List[PurePath] = []
                try:
                    # Launch the whole VM batch promptly, without any per-VM
                    # blocking wait, so VMs run concurrently.
                    for i in range(vm_count):
                        vm_disk_img_path = disk_img_files[i]
                        vm_log_file_path = (
                            disk_img_copy_path
                            / f"CH_VM{i}_cfg{config_id}_iter{test_iter}.log"
                        )
                        log_files.append(vm_log_file_path)
                        created_logs.append(vm_log_file_path)
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
                        # Track the process before any check so cleanup can tear
                        # it (and every earlier VM) down if a later step raises.
                        procs.append(p)
                    node.tools[Free].log_memory_stats_mb()

                    # Original total keep-running duration (do not extend it).
                    sleep_time = 10
                    if guest_vm_type == "CVM":
                        # CVM guest take little more time to boot
                        # 20 seconds per VM (with default 1024M)
                        sleep_time = 20 * vm_count

                    # One shared, bounded startup grace for the whole batch,
                    # taken out of the keep-running duration.
                    grace = min(self.STARTUP_GRACE_SECONDS, sleep_time)
                    time.sleep(grace)
                    self._check_early_exits(
                        procs, log_files, node, log_path, log, guest_vm_type, "startup"
                    )

                    # Keep the VMs running for the remainder of the duration.
                    remaining = sleep_time - grace
                    if remaining > 0:
                        time.sleep(remaining)

                    # Re-inspect at pre-stop so a VM that exited *after* the
                    # startup grace is still captured and classified exactly.
                    # An unknown failure here is counted (not raised) so the
                    # remaining iterations still run and the config is failed
                    # once at the end, matching the original behavior.
                    pre_stop_failures += self._check_early_exits(
                        procs, log_files, node, log_path, log, guest_vm_type, "pre-stop"
                    )

                    for i, p in enumerate(procs):
                        # Never signal a process that has already exited (e.g. a
                        # VM counted as a pre-stop failure above).
                        if p.is_running():
                            log.info(f"Killing VM {i}")
                            p.kill()

                    if guest_vm_type == "CVM":
                        # CVM guest killing takes sometime
                        time.sleep(20)

                    node.tools[Free].log_memory_stats_mb()
                finally:
                    # Ensure any VM still running in this iteration (including
                    # already-running VMs when a later one failed or skipped) is
                    # torn down before the next iteration or before propagating.
                    self._kill_running_procs(procs, log)

            # All iterations have run. Fail the config now if any VM died
            # unexpectedly after its keep-running period during the run.
            assert_that(pre_stop_failures).described_as(
                f"{pre_stop_failures} VM(s) exited unexpectedly after the "
                "keep-running period across all iterations"
            ).is_equal_to(0)
        finally:
            self._cleanup_vm_artifacts(
                node, disk_img_files, created_logs, log_path, log
            )

    def _check_early_exits(
        self,
        procs: List[Process],
        log_files: List[PurePath],
        node: Node,
        log_path: Path,
        log: Logger,
        guest_vm_type: str,
        phase: str,
    ) -> int:
        # Inspect, capture and classify every process that has already exited.
        #
        # Hard (unknown) failures dominate an unsupported classification within
        # a single batch. How a hard failure is surfaced depends on the phase:
        #   * "startup": fail fast -- raise LisaException immediately so we do
        #     not keep creating VMs on a host that cannot even start them.
        #   * "pre-stop"/post-run: a VM that dies only after the keep-running
        #     period is an intermittent/unknown failure. Do NOT raise; return
        #     the count so the caller can keep running the remaining iterations
        #     and fail the whole config once, after all iterations complete.
        # Exact CVM unsupported signatures are always skipped immediately, but
        # only when no hard failure in the same batch dominates them.
        unsupported_message: Optional[str] = None
        hard_failures: List[str] = []
        for i, p in enumerate(procs):
            if p.is_running():
                continue
            log.info(f"VM {i} exited during the {phase} window")
            result = p.wait_result(timeout=self.STARTUP_RESULT_TIMEOUT)
            # Always preserve the exited VM's log before deciding pass/skip/fail.
            self._preserve_vm_log(node, log_files[i], log_path, log)
            output = f"{result.stdout}\n{result.stderr}"
            # Only confidential VMs (CVM) treat a VmCreate + EINVAL on the same
            # line as an unsupported host/kernel/MSHV combination. For standard
            # (NON-CVM) VMs any early exit is a genuine failure.
            if guest_vm_type == "CVM" and self._matches_unsupported_vm_create(output):
                unsupported_message = self._format_unsupported_message(
                    i, result, node, log
                )
                continue
            hard_failures.append(
                f"VM {i} exited during {phase} with exit code "
                f"{result.exit_code}. cloud-hypervisor output: "
                f"{output.strip()[-2000:]}"
            )
        if hard_failures:
            # Hard failures dominate an unsupported classification in this batch.
            if phase == "startup":
                raise LisaException("; ".join(hard_failures))
            for message in hard_failures:
                log.error(message)
            return len(hard_failures)
        if unsupported_message is not None:
            raise SkippedException(unsupported_message)
        return 0

    def _matches_unsupported_vm_create(self, output: str) -> bool:
        # The unsupported signature must have VmCreate and an EINVAL indicator on
        # the *same* line/context; matches split across lines are near misses
        # and must not be treated as unsupported.
        if not output:
            return False
        for line in output.splitlines():
            lowered = line.lower()
            if "vmcreate" in lowered and any(
                indicator in lowered for indicator in self._EINVAL_INDICATORS
            ):
                return True
        return False

    def _format_unsupported_message(
        self,
        index: int,
        result: ExecutableResult,
        node: Node,
        log: Logger,
    ) -> str:
        details = [
            f"VM {index} could not be created: cloud-hypervisor reported "
            "VmCreate with EINVAL (Invalid argument / os error 22). The current "
            "host/kernel/MSHV/cloud-hypervisor combination does not support "
            "creating the requested confidential VM (CVM) configuration."
        ]
        if result.exit_code is not None:
            details.append(f"cloud-hypervisor exit code: {result.exit_code}")
        try:
            kernel = node.tools[Uname].get_linux_information().kernel_version_raw
            if kernel:
                details.append(f"kernel: {kernel}")
        except LisaException as e:
            log.debug(f"Unable to collect kernel version for skip evidence: {e}")
        output = f"{result.stdout}\n{result.stderr}".strip()
        if output:
            details.append(f"cloud-hypervisor output: {output[-1000:]}")
        return " | ".join(details)

    def _preserve_vm_log(
        self,
        node: Node,
        remote_log_path: PurePath,
        log_path: Path,
        log: Logger,
    ) -> None:
        # cloud-hypervisor runs under sudo, so its --log-file is root-owned and
        # cannot be read by the SSH user that copy_back runs as. Stage a
        # world-readable copy in the user-owned working path first, then copy it
        # back. Any failure to preserve evidence must be visible as a warning.
        local_name = PurePath(remote_log_path).name
        # Stage under a distinct name so the staged copy can never collide with
        # the original log. When the disk-image copy path falls back to the
        # working path, remote_log_path already lives under node.working_path;
        # a plain same-name staged copy would then equal the original and the
        # cleanup below would delete the very evidence we are trying to keep.
        # The ".staged_" prefix guarantees staged != remote_log_path, so staging
        # cleanup only ever removes the staged copy and always retains the
        # original for a later retry.
        staged = node.working_path / f".staged_{local_name}"
        try:
            if not node.tools[Ls].path_exists(str(remote_log_path), sudo=True):
                log.debug(f"VM log not present, nothing to preserve: {remote_log_path}")
                return
            # Assert the staging commands actually succeed (expected_exit_code
            # raises AssertionError otherwise) so we never copy_back a stale or
            # missing file and silently believe evidence was preserved.
            node.execute(
                f"cp -f '{remote_log_path}' '{staged}'",
                sudo=True,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to stage VM log {remote_log_path}"
                ),
            )
            node.execute(
                f"chmod a+r '{staged}'",
                sudo=True,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to make staged VM log readable: {staged}"
                ),
            )
            local_path = log_path / local_name
            node.shell.copy_back(staged, local_path)
            log.debug(f"Preserved VM log {remote_log_path} -> {local_path}")
        except _OPERATIONAL_ERRORS as e:
            # Leave the original remote log in place so the final cleanup pass
            # can retry preserving it.
            log.warning(f"Failed to preserve VM log {remote_log_path}: {e}")
        finally:
            # Only the distinct staged copy is removed here; the original log is
            # never touched by staging.
            self._best_effort_remove(node, staged, log)

    def _kill_running_procs(self, procs: List[Process], log: Logger) -> None:
        for i, p in enumerate(procs):
            try:
                if p is not None and p.is_running():
                    log.info(f"Cleaning up running VM {i}")
                    p.kill()
            except _OPERATIONAL_ERRORS as e:
                log.debug(f"Failed to kill VM {i} during cleanup: {e}")

    def _best_effort_remove(self, node: Node, path: PurePath, log: Logger) -> None:
        try:
            node.tools[Rm].remove_file(str(path), sudo=True)
        except _OPERATIONAL_ERRORS as e:
            log.debug(f"Failed to remove {path} during cleanup: {e}")

    def _cleanup_vm_artifacts(
        self,
        node: Node,
        disk_img_files: List[PurePath],
        created_logs: List[PurePath],
        log_path: Path,
        log: Logger,
    ) -> None:
        # Preserve every per-iteration log (unique names, so earlier failure
        # evidence is never overwritten) before removing it, then drop the disk
        # copies.
        for log_file in created_logs:
            self._preserve_vm_log(node, log_file, log_path, log)
            self._best_effort_remove(node, log_file, log)
        for disk_img_file in disk_img_files:
            self._best_effort_remove(node, disk_img_file, log)

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
        except _OPERATIONAL_ERRORS as e:
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
