# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Set, Tuple

from assertpy import assert_that
from microsoft.testsuites.mshv.bpftrace_tool import Bpftrace, HypercallTraceSession
from microsoft.testsuites.mshv.cloud_hypervisor_tool import CloudHypervisor

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import (
    Cat,
    Cp,
    Df,
    Dmesg,
    Free,
    Kill,
    Ls,
    Lsblk,
    Lscpu,
    Mount,
    QemuImg,
    Ssh,
    Stat,
    Usermod,
    Wget,
)
from lisa.tools.lsblk import DiskInfo
from lisa.tools.mkfs import FileSystem
from lisa.util import LisaException, SkippedException
from lisa.util.process import Process

_DMESG_TIMESTAMP_PATTERN = re.compile(r"^\[\s*(\d+\.\d+)\]")
_DRIVER_LINE_PATTERN = re.compile(r"mshv|hv_call|hyper-?v|HV_STATUS", re.IGNORECASE)
_ERROR_TERMS_PATTERN = re.compile(
    r"fail|error|unable|cannot|denied|invalid|insufficient|HV_STATUS",
    re.IGNORECASE,
)


@dataclass
class _VmCreateIterationResult:
    iteration: int
    guest_config: str
    attempted: int = 0
    booted: int = 0
    # cap_reached | launch_failure | harness_error
    stop_reason: str = ""
    # e.g. "VM12@launch"
    first_failure: str = "-"
    vmm_error: str = "-"
    driver_errors: List[str] = field(default_factory=list)
    hv_status: List[str] = field(default_factory=list)
    hv_call_errors: List[str] = field(default_factory=list)
    runtime_exits: int = 0
    leaked_vmm_processes: int = 0
    trace_state: str = "disabled"

    def signature(self, include_trace: bool) -> Dict[str, Any]:
        # Booted count is compared separately so a tolerance can be applied.
        # Failing VM index is implied by it, so only the stage is kept.
        signature: Dict[str, Any] = {
            "stop_reason": self.stop_reason,
            "first_failure_stage": self.first_failure.partition("@")[2] or "-",
            "vmm_error": self.vmm_error,
            "runtime_exits": self.runtime_exits,
        }
        if include_trace:
            signature["hv_status"] = self.hv_status
            signature["hv_call_errors"] = self.hv_call_errors
        return signature


_VOLATILE_FIELD_PATTERNS: List[Tuple["re.Pattern[str]", str]] = [
    # Absolute paths carry per-VM file names.
    (re.compile(r"(?<![\w.])/(?:[\w.+-]+/)*[\w.+-]+"), "<path>"),
    # Process/thread IDs.
    (re.compile(r"\b(pid|tid)([:=\s]\s*)\d+(?!\w)", re.IGNORECASE), r"\1\2#"),
    # Rust panic messages carry the OS thread id.
    (re.compile(r"(\bthread '[^']*' )\(\d+\)"), r"\1(#)"),
    # Hypervisor partition IDs, e.g. "partition 42" or the "p42:" prefix.
    (
        re.compile(
            r"\b(partition(?:[ _]id)?|pt_id)([:=\s]\s*)\d+(?!\w)", re.IGNORECASE
        ),
        r"\1\2#",
    ),
    (re.compile(r"(?<![\w])p\d+:"), "p#:"),
    # Guest/host memory locations reported by mshv region and intercept
    # errors.
    (
        re.compile(
            r"\b(region|range|pages|gfn|gpa|mm|addr|address)([:=\s]\s*)"
            r"0x[0-9a-fA-F]+(?:-0x[0-9a-fA-F]+)?",
            re.IGNORECASE,
        ),
        r"\1\2<addr>",
    ),
    # Kernel/user pointers (raw and %p-hashed).
    (re.compile(r"\b0x[0-9a-fA-F]{12,}\b"), "<addr>"),
    (re.compile(r"\b[0-9a-fA-F]{16}\b"), "<addr>"),
    # cloud-hypervisor auto-generates a tap device and MAC for each guest.
    (re.compile(r"\bvmtap\d+\b"), "vmtap#"),
    (re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b"), "<mac>"),
]


def _normalize_error_line(line: str) -> str:
    # Strip only volatile identifiers (timestamps, paths, pids, partition
    # ids, addresses, tap/MAC) so the same failure produces the same text in
    # every iteration.
    line = _DMESG_TIMESTAMP_PATTERN.sub("", line.strip())
    line = re.sub(r"^\s*\[\s*[TC]\d+\]\s*", "", line)
    line = re.sub(r"^cloud-hypervisor:\s*[\d.]+\w*:\s*", "", line)
    for pattern, replacement in _VOLATILE_FIELD_PATTERNS:
        line = pattern.sub(replacement, line)
    return re.sub(r"\s+", " ", line).strip()


def _get_last_dmesg_timestamp(dmesg: str) -> float:
    last = 0.0
    for line in dmesg.splitlines():
        match = _DMESG_TIMESTAMP_PATTERN.match(line)
        if match:
            last = float(match.group(1))
    return last


def _get_driver_errors(dmesg: str, since: float) -> List[str]:
    errors: Set[str] = set()
    for line in dmesg.splitlines():
        match = _DMESG_TIMESTAMP_PATTERN.match(line)
        if not match or float(match.group(1)) <= since:
            continue
        if _DRIVER_LINE_PATTERN.search(line) and _ERROR_TERMS_PATTERN.search(line):
            errors.add(_normalize_error_line(line))
    return sorted(errors)


def _evaluate_iterations(
    results: List[_VmCreateIterationResult],
    min_vms: int,
    allowed_deviation: int,
) -> List[str]:
    problems: List[str] = []
    for r in results:
        if r.booted < min_vms:
            problems.append(
                f"iteration {r.iteration}: booted {r.booted} guest(s), "
                f"expected at least {min_vms}"
            )
        if r.stop_reason == "harness_error":
            problems.append(
                f"iteration {r.iteration}: failed to start VMM: {r.vmm_error}"
            )
        if r.leaked_vmm_processes:
            problems.append(
                f"iteration {r.iteration}: {r.leaked_vmm_processes} "
                "cloud-hypervisor process(es) left after teardown"
            )

    baseline = results[0]
    for r in results[1:]:
        if abs(r.booted - baseline.booted) > allowed_deviation:
            problems.append(
                f"iteration {r.iteration}: booted {r.booted}, "
                f"iteration 1 booted {baseline.booted}"
            )
        include_trace = baseline.trace_state == "ok" and r.trace_state == "ok"
        expected = baseline.signature(include_trace)
        actual = r.signature(include_trace)
        for key, value in actual.items():
            if value != expected[key]:
                problems.append(
                    f"iteration {r.iteration}: {key}={value}, "
                    f"iteration 1 {key}={expected[key]}"
                )
    return problems


def _format_matrix(results: List[_VmCreateIterationResult]) -> str:
    headers = [
        "Iter",
        "Guest config",
        "Attempted",
        "Booted",
        "Stop reason",
        "First failure",
        "VMM error",
        "Driver errors",
        "HV status",
        "hv_call/ioctl errors",
        "Runtime exits",
        "Leaked VMMs",
        "Trace",
    ]
    rows = [
        [
            str(r.iteration),
            r.guest_config,
            str(r.attempted),
            str(r.booted),
            r.stop_reason,
            r.first_failure,
            r.vmm_error,
            "; ".join(r.driver_errors) or "-",
            ", ".join(r.hv_status) or "-",
            ", ".join(r.hv_call_errors) or "-",
            str(r.runtime_exits),
            str(r.leaked_vmm_processes),
            r.trace_state,
        ]
        for r in results
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend(
        "| " + " | ".join(cell.replace("|", "/") for cell in row) + " |" for row in rows
    )
    return "\n".join(lines) + "\n"


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
    DEFAULT_MIN_VMS = 1
    DEFAULT_BOOT_CHECK_SECONDS = 3
    DEFAULT_CVM_BOOT_CHECK_SECONDS = 10
    TEARDOWN_SETTLE_SECONDS = 5
    HOLD_SECONDS = 10
    CVM_BOOT_SECONDS_PER_VM = 20
    VMM_STOP_TIMEOUT_SECONDS = 60
    HOST_MEM_RESERVE_MB = 2048
    DISK_RESERVE_MB = 1024
    MAX_ERROR_LENGTH = 400
    CGROUP_ROOT = "/sys/fs/cgroup"
    WORKLOAD_CGROUP_NAME = "lisa_mshv_stress"
    _VMM_ERROR_PATTERN = re.compile(
        r"error|fail|denied|unable|cannot|panic", re.IGNORECASE
    )

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
        Stress the MSHV virt stack by repeatedly booting as many identical
        guests as the host accepts and checking that the outcome is
        consistent across iterations.

        The number of guests a host can boot is not always derivable from the
        node: e.g. on L1VH/nested hosts the parent hypervisor caps the number
        of guest partitions and that limit is not exposed. So instead of
        asserting a computed count, each iteration:
        1. Starts a bpftrace session (if available) that records raw HV
           status codes from hv_result_to_errno() and failing hv_call_* /
           mshv ioctl return values. The test VMMs run in a dedicated cgroup
           v2 group and only their events are counted, on hosts without
           cgroup v2 the trace is recorded but not compared.
        2. Launches guests (default 1 vCPU / 1 GiB) back to back until one
           exits or a cap is reached, then gives all of them one shared
           "boot_check_seconds" window; the lowest-index guest that exited is
           the first failure. The cap defaults to
           host threads / cpus_per_vm, bounded by available memory and disk.
        3. Keeps the guests running briefly, then tears them down and makes
           sure no cloud-hypervisor process is leaked.
        4. Records: guest config, guests booted, first failure, VMM error,
           mshv driver errors (dmesg) and hypercall return codes. Driver
           errors are host-wide, so they are kept as diagnostics and not
           compared.

        The test fails if any iteration boots fewer than "min_vms" guests,
        leaks VMM processes, or deviates from the first iteration (booted
        count beyond "allowed_count_deviation" or a different failure
        signature). The per-iteration matrix is saved to the log folder.

        Configurable per entry of "mshv_vm_create_stress_configs":
        iterations, cpus_per_vm, mem_per_vm_mb, max_vms, min_vms,
        boot_check_seconds, allowed_count_deviation, enable_bpftrace.
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

        failed: List[str] = []
        skipped: List[str] = []
        passed = 0
        for config_index, config in enumerate(configs, start=1):
            times = config.get("iterations", self.DEFAULT_ITERS)
            cpus_per_vm = config.get("cpus_per_vm", self.DEFAULT_CPUS_PER_VM)
            mem_per_vm_mb = config.get("mem_per_vm_mb", self.DEFAULT_MEM_PER_VM_MB)
            test_name = (
                f"mshv_stress_vm_create_cfg{config_index}_{times}times_"
                f"{cpus_per_vm}cpu_{mem_per_vm_mb}MB"
            )
            try:
                summary = self._mshv_stress_vm_create(
                    test_name=test_name,
                    times=times,
                    cpus_per_vm=cpus_per_vm,
                    mem_per_vm_mb=mem_per_vm_mb,
                    config=config,
                    log=log,
                    node=node,
                    log_path=log_path,
                    guest_vm_type=guest_vm_type,
                    igvm_path=igvm_path,
                )
                passed += 1
                send_sub_test_result_message(
                    test_result=result,
                    test_case_name=test_name,
                    test_status=TestStatus.PASSED,
                    test_message=summary,
                )
            except SkippedException as e:
                skipped.append(f"{test_name}: {e}")
                log.info(f"{test_name} SKIPPED: {e}")
                send_sub_test_result_message(
                    test_result=result,
                    test_case_name=test_name,
                    test_status=TestStatus.SKIPPED,
                    test_message=str(e),
                )
            except Exception as e:
                failed.append(test_name)
                log.error(f"{test_name} FAILED: {e}")
                send_sub_test_result_message(
                    test_result=result,
                    test_case_name=test_name,
                    test_status=TestStatus.FAILED,
                    test_message=repr(e),
                )
        ch_tool: CloudHypervisor = node.tools[CloudHypervisor]
        ch_tool.save_dmesg_logs(node, log_path)
        assert_that(failed).described_as("failed stress configurations").is_empty()
        # Subtest SKIPPED messages do not change the parent status, so a run
        # where no configuration executed must be skipped explicitly.
        if not passed:
            raise SkippedException(
                "no stress configuration ran: " + ("; ".join(skipped) or "none given")
            )

    def _mshv_stress_vm_create(
        self,
        test_name: str,
        times: int,
        cpus_per_vm: int,
        mem_per_vm_mb: int,
        config: Dict[str, Any],
        log: Logger,
        node: Node,
        log_path: Path,
        guest_vm_type: str = "NON-CVM",
        igvm_path: str = "",
    ) -> str:
        is_cvm = guest_vm_type == "CVM"
        min_vms = int(config.get("min_vms", self.DEFAULT_MIN_VMS))
        boot_check_seconds = float(
            config.get(
                "boot_check_seconds",
                self.DEFAULT_CVM_BOOT_CHECK_SECONDS
                if is_cvm
                else self.DEFAULT_BOOT_CHECK_SECONDS,
            )
        )
        allowed_deviation = int(config.get("allowed_count_deviation", 0))
        log.info(
            f"MSHV stress VM create: times={times}, cpus_per_vm={cpus_per_vm}, "
            f"mem_per_vm_mb={mem_per_vm_mb}, min_vms={min_vms}, "
            f"boot_check_seconds={boot_check_seconds}, "
            f"allowed_count_deviation={allowed_deviation}"
        )
        disk_img_path = node.get_working_path() / self.DISK_IMG_NAME
        disk_img_copy_path = self._get_disk_img_copy_path(node, log)
        max_vms = self._get_max_vm_count(
            node=node,
            log=log,
            cpus_per_vm=cpus_per_vm,
            mem_per_vm_mb=mem_per_vm_mb,
            disk_img_path=disk_img_path,
            disk_img_copy_path=disk_img_copy_path,
            requested_max_vms=config.get("max_vms"),
        )
        if max_vms < min_vms:
            raise SkippedException(
                f"host resources allow only {max_vms} guest(s) of "
                f"{cpus_per_vm} vCPU/{mem_per_vm_mb} MB, min_vms is {min_vms}"
            )

        tracer = (
            self._get_tracer(node, log) if config.get("enable_bpftrace", True) else None
        )
        workload_cgroup = self._create_workload_cgroup(node, log)
        results: List[_VmCreateIterationResult] = []
        try:
            for test_iter in range(times):
                log.info(f"Test iteration {test_iter + 1} of {times}")
                iteration_result = self._run_vm_create_iteration(
                    iteration=test_iter + 1,
                    max_vms=max_vms,
                    cpus_per_vm=cpus_per_vm,
                    mem_per_vm_mb=mem_per_vm_mb,
                    boot_check_seconds=boot_check_seconds,
                    log=log,
                    node=node,
                    log_path=log_path,
                    disk_img_path=disk_img_path,
                    disk_img_copy_path=disk_img_copy_path,
                    guest_vm_type=guest_vm_type,
                    igvm_path=igvm_path,
                    tracer=tracer,
                    workload_cgroup=workload_cgroup,
                )
                log.info(f"Iteration result: {iteration_result}")
                results.append(iteration_result)
        finally:
            if workload_cgroup:
                node.execute(f"rmdir {workload_cgroup}", sudo=True, no_error_log=True)
            node.execute(
                f"rm -f {disk_img_copy_path}/VM*_{self.DISK_IMG_NAME} "
                f"{disk_img_copy_path}/CH_VM*.log {disk_img_copy_path}/CH_VM*.pid",
                shell=True,
                sudo=True,
            )
            if results:
                self._save_matrix(results, test_name, log_path, log)

        problems = _evaluate_iterations(results, min_vms, allowed_deviation)
        baseline = results[0]
        summary = (
            f"{len(results)} iterations, guest={baseline.guest_config}, "
            f"booted={baseline.booted} (cap {max_vms}), "
            f"stop={baseline.stop_reason}, first_failure={baseline.first_failure}, "
            f"hv_status={baseline.hv_status or '-'}"
        )
        if problems:
            raise LisaException(
                f"{summary}. Inconsistent results: " + "; ".join(problems)
            )
        log.info(f"{test_name}: consistent results: {summary}")
        return summary

    def _run_vm_create_iteration(
        self,
        iteration: int,
        max_vms: int,
        cpus_per_vm: int,
        mem_per_vm_mb: int,
        boot_check_seconds: float,
        log: Logger,
        node: Node,
        log_path: Path,
        disk_img_path: PurePath,
        disk_img_copy_path: PurePath,
        guest_vm_type: str,
        igvm_path: str,
        tracer: Optional[Bpftrace],
        workload_cgroup: str = "",
    ) -> "_VmCreateIterationResult":
        is_cvm = guest_vm_type == "CVM"
        hypervisor_fw_path = str(node.get_working_path() / self.HYPERVISOR_FW_NAME)
        result = _VmCreateIterationResult(
            iteration=iteration,
            guest_config=f"{cpus_per_vm}vCPU/{mem_per_vm_mb}MB/{guest_vm_type}",
        )
        node.tools[Free].log_memory_stats_mb()
        dmesg_mark = _get_last_dmesg_timestamp(
            node.tools[Dmesg].get_output(force_run=True)
        )

        trace_session: Optional[HypercallTraceSession] = None
        ch_tool: CloudHypervisor = node.tools[CloudHypervisor]
        if tracer:
            try:
                trace_session = tracer.start_hypercall_trace(
                    str(node.get_working_path()),
                    f"mshv_stress_iter{iteration}",
                    cgroup_path=workload_cgroup,
                )
                # Unscoped traces may include other VMMs' errors, so they are
                # recorded but not compared across iterations.
                result.trace_state = "ok" if workload_cgroup else "unscoped"
            except Exception as e:
                result.trace_state = f"failed: {e}"
                log.info(f"bpftrace not started for iteration {iteration}: {e}")
        procs: List[Process] = []
        booted_procs: List[Tuple[int, Process]] = []
        # pid file -> VMM log file, for every VMM launched in this iteration.
        launched_vmms: Dict[str, str] = {}
        first_launch_time: Optional[float] = None
        last_launch_time: Optional[float] = None
        launched: List[Tuple[int, Process]] = []
        try:
            for i in range(max_vms):
                if any(not p.is_running() for _, p in launched):
                    break
                vm_disk_img_path = disk_img_copy_path / f"VM{i}_{self.DISK_IMG_NAME}"
                vm_log_file_path = disk_img_copy_path / f"CH_VM{i}.log"
                vm_pid_file_path = disk_img_copy_path / f"CH_VM{i}.pid"
                if not node.tools[Ls].path_exists(str(vm_disk_img_path)):
                    node.tools[Cp].copy(
                        disk_img_path,
                        vm_disk_img_path,
                        sudo=True,
                        timeout=1200,
                    )
                result.attempted += 1
                log.info(f"Starting VM {i}")
                if first_launch_time is None:
                    first_launch_time = time.time()
                launched_vmms[str(vm_pid_file_path)] = str(vm_log_file_path)
                try:
                    p = ch_tool.start_vm_async(
                        kernel=hypervisor_fw_path,
                        cpus=cpus_per_vm,
                        memory_mb=mem_per_vm_mb,
                        disk_path=str(vm_disk_img_path),
                        sudo=True,
                        guest_vm_type=guest_vm_type,
                        igvm_path=igvm_path,
                        log_file=str(vm_log_file_path),
                        cgroup=workload_cgroup,
                        pid_file=str(vm_pid_file_path),
                    )
                except Exception as e:
                    result.stop_reason = "harness_error"
                    result.first_failure = f"VM{i}@start"
                    result.vmm_error = _normalize_error_line(str(e))
                    break
                procs.append(p)
                launched.append((i, p))
                last_launch_time = time.time()

            if last_launch_time is not None:
                time.sleep(
                    max(0.0, last_launch_time + boot_check_seconds - time.time())
                )
            booted_procs = self._classify_launches(
                node, result, launched, disk_img_copy_path, log_path, log
            )

            time.sleep(
                self._get_hold_seconds(
                    first_launch_time=first_launch_time,
                    booted_count=len(booted_procs),
                    is_cvm=is_cvm,
                )
            )

            for i, p in booted_procs:
                if p.is_running():
                    result.booted += 1
                    continue
                log.info(f"VM {i} exited while running")
                result.runtime_exits += 1
                if result.first_failure == "-":
                     result.first_failure = f"VM{i}@runtime"
                if result.vmm_error == "-":
                    result.vmm_error = self._collect_vmm_error(
                        node,
                        p,
                        disk_img_copy_path / f"CH_VM{i}.log",
                        log_path,
                    )
        finally:
            result.leaked_vmm_processes = self._stop_all_vms(
                node, procs, workload_cgroup, launched_vmms, log
            )
            # Give the hypervisor time to finish tearing down partitions so
            # the next iteration starts from the same state.
            time.sleep(20 if is_cvm else self.TEARDOWN_SETTLE_SECONDS)
            if tracer and trace_session:
                try:
                    trace = tracer.stop_hypercall_trace(trace_session)
                    result.hv_status = sorted(trace.hv_status)
                    result.hv_call_errors = sorted(trace.call_errors)
                except Exception as e:
                    result.trace_state = f"failed: {e}"
            result.driver_errors = _get_driver_errors(
                node.tools[Dmesg].get_output(force_run=True), dmesg_mark
            )

        node.tools[Free].log_memory_stats_mb()
        return result

    @classmethod
    def _get_hold_seconds(
        cls,
        first_launch_time: Optional[float],
        booted_count: int,
        is_cvm: bool,
        now: Optional[float] = None,
    ) -> float:
        # Keep the guests running for at least HOLD_SECONDS after the boot
        # check. CVM guests also need about CVM_BOOT_SECONDS_PER_VM each (with
        # the default 1024M) to boot; that budget is counted from the first
        # launch, so time already spent launching is not waited again.
        hold = float(cls.HOLD_SECONDS)
        if is_cvm and first_launch_time is not None:
            elapsed = (now if now is not None else time.time()) - first_launch_time
            hold = max(hold, cls.CVM_BOOT_SECONDS_PER_VM * booted_count - elapsed)
        return hold

    def _classify_launches(
        self,
        node: Node,
        result: "_VmCreateIterationResult",
        launched: List[Tuple[int, Process]],
        disk_img_copy_path: PurePath,
        log_path: Path,
        log: Logger,
    ) -> List[Tuple[int, Process]]:
        exited = [(i, p) for i, p in launched if not p.is_running()]
        if exited and not result.stop_reason:
            # Launches continue for a moment after the limit is hit, so
            # several guests may fail; the lowest index is the first failure.
            i, p = exited[0]
            log.info(
                f"VM {i} exited during launch "
                f"({len(exited)} of {len(launched)} launched guests exited)"
            )
            result.stop_reason = "launch_failure"
            result.first_failure = f"VM{i}@launch"
            result.vmm_error = self._collect_vmm_error(
                node, p, disk_img_copy_path / f"CH_VM{i}.log", log_path
            )
        elif not result.stop_reason:
            result.stop_reason = "cap_reached"
        return [(i, p) for i, p in launched if (i, p) not in exited]

    def _collect_vmm_error(
        self,
        node: Node,
        process: Process,
        vm_log_file_path: PurePath,
        log_path: Path,
    ) -> str:
        output = ""
        exit_code: Optional[int] = None
        try:
            vmm_result = process.wait_result(timeout=30, raise_on_timeout=False)
            exit_code = vmm_result.exit_code
            output = f"{vmm_result.stderr}\n{vmm_result.stdout}"
        except Exception as e:
            output = str(e)
        try:
            output += "\n" + node.tools[Cat].read(
                str(vm_log_file_path), sudo=True, force_run=True
            )
            node.shell.copy_back(vm_log_file_path, log_path / vm_log_file_path.name)
        except Exception as e:
            node.log.debug(f"failed to fetch {vm_log_file_path}: {e}")

        errors: List[str] = []
        for line in output.splitlines():
            if self._VMM_ERROR_PATTERN.search(line):
                normalized = _normalize_error_line(line)
                if normalized and normalized not in errors:
                    errors.append(normalized)
        if not errors:
            return f"exit_code={exit_code}"
        return " | ".join(errors)[: self.MAX_ERROR_LENGTH]

    def _stop_all_vms(
        self,
        node: Node,
        procs: List[Process],
        workload_cgroup: str,
        launched_vmms: Dict[str, str],
        log: Logger,
    ) -> int:
        for p in procs:
            if p.is_running():
                p.kill()

        # Process.kill() kills the sudo wrapper, make sure the actual VMM
        # processes are gone so the next iteration starts from a clean host.
        leftovers: List[str] = []
        deadline = time.time() + self.VMM_STOP_TIMEOUT_SECONDS
        while time.time() < deadline:
            leftovers = self._get_workload_vmm_pids(
                node, workload_cgroup, launched_vmms
            )
            if not leftovers:
                break
            for pid in leftovers:
                try:
                    node.tools[Kill].by_pid(pid, ignore_not_exist=True)
                except Exception as e:
                    log.debug(f"failed to kill VMM pid {pid}: {e}")
            time.sleep(2)
        leftovers = self._get_workload_vmm_pids(
             node, workload_cgroup, launched_vmms
        )
        if leftovers:
            log.error(f"cloud-hypervisor processes still running: {leftovers}")
        # Drop this iteration's pid files so a recycled PID can never be
        # attributed to the workload later.
        if launched_vmms:
            node.execute(
                "rm -f " + " ".join(launched_vmms), sudo=True, no_error_log=True
            )
        return len(leftovers)

    def _get_workload_vmm_pids(
        self, node: Node, workload_cgroup: str, launched_vmms: Dict[str, str]
    ) -> List[str]:
        if workload_cgroup:
            output = node.execute(
                f"cat {workload_cgroup}/cgroup.procs", sudo=True, no_error_log=True
            ).stdout
            return [pid for pid in output.split() if pid.isdigit()]

        # Without a cgroup, use the PIDs recorded at launch. A PID only
        # counts while it still runs a VMM with this VM's own log file, so a
        # recycled PID is never mistaken for one of ours.
        pids: List[str] = []
        for pid_file, vm_log_file in launched_vmms.items():
            output = node.execute(
                f'pid=$(cat {pid_file} 2>/dev/null) && [ -n "$pid" ] && '
                f"tr '\\0' ' ' < /proc/$pid/cmdline && echo && echo $pid",
                shell=True,
                sudo=True,
                no_error_log=True,
            ).stdout.strip()
            lines = output.splitlines()
            if len(lines) >= 2 and lines[-1].isdigit():
                cmdline = " ".join(lines[:-1])
                if f"--log-file {vm_log_file}" in cmdline:
                    pids.append(lines[-1])
        return pids

    def _create_workload_cgroup(self, node: Node, log: Logger) -> str:
        # A dedicated cgroup v2 group lets bpftrace attribute mshv errors to
        # this test's VMMs only, not to pre-existing ones on the host.
        root = self.CGROUP_ROOT
        fs_type = node.execute(
            f"stat -fc %T {root}", sudo=True, no_error_log=True
        ).stdout.strip()
        if fs_type != "cgroup2fs":
            log.info(
                f"{root} is '{fs_type}', not cgroup v2, hypercall traces will "
                "not be scoped to the test VMMs and are excluded from comparison"
            )
            return ""
        path = f"{root}/{self.WORKLOAD_CGROUP_NAME}"
        check = node.execute(
            f"mkdir -p {path} && echo $$ > {path}/cgroup.procs",
            shell=True,
            sudo=True,
            no_error_log=True,
        )
        if check.exit_code != 0:
            log.info(
                f"cannot use cgroup {path} ({check.stdout.strip()}), hypercall "
                "traces will not be scoped and are excluded from comparison"
            )
            node.execute(f"rmdir {path}", sudo=True, no_error_log=True)
            return ""
        return path

    def _get_tracer(self, node: Node, log: Logger) -> Optional[Bpftrace]:
        try:
            tracer: Bpftrace = node.tools[Bpftrace]
            tracer.build_hypercall_script()
            return tracer
        except Exception as e:
            log.info(f"bpftrace hypercall tracing disabled: {e}")
            return None

    def _get_max_vm_count(
        self,
        node: Node,
        log: Logger,
        cpus_per_vm: int,
        mem_per_vm_mb: int,
        disk_img_path: PurePath,
        disk_img_copy_path: PurePath,
        requested_max_vms: Optional[Any],
    ) -> int:
        # The cap is computed once per config so every iteration probes the
        # same range, hitting it is a valid, consistent outcome.
        if requested_max_vms:
            requested = int(requested_max_vms)
        else:
            requested = node.tools[Lscpu].get_thread_count() // cpus_per_vm

        mem_available_mb = (
            int(
                node.execute(
                    "awk '/^MemAvailable:/ {print $2}' /proc/meminfo",
                    shell=True,
                    expected_exit_code=0,
                ).stdout.strip()
            )
            // 1024
        )
        mem_cap = max(0, mem_available_mb - self.HOST_MEM_RESERVE_MB) // mem_per_vm_mb

        img_bytes = node.tools[Stat].get_total_size(str(disk_img_path), sudo=True)
        img_mb = max(1, -(-img_bytes // (1024 * 1024)))
        existing_copies = int(
            node.execute(
                f"ls {disk_img_copy_path} | grep -c '^VM[0-9]*_{self.DISK_IMG_NAME}$'",
                shell=True,
            ).stdout.strip()
            or 0
        )
        disk_available_mb = int(
            node.tools[Df].get_filesystem_available_space(
                str(disk_img_copy_path), force_run=True
            )
            * 1024
        )
        disk_cap = (
            existing_copies + max(0, disk_available_mb - self.DISK_RESERVE_MB) // img_mb
        )

        max_vms = max(0, min(requested, mem_cap, disk_cap))
        log.info(
            f"VM cap: {max_vms} (requested={requested}, memory_cap={mem_cap}, "
            f"disk_cap={disk_cap}, mem_available_mb={mem_available_mb}, "
            f"disk_available_mb={disk_available_mb}, image_mb={img_mb})"
        )
        return max_vms

    def _save_matrix(
        self,
        results: List["_VmCreateIterationResult"],
        test_name: str,
        log_path: Path,
        log: Logger,
    ) -> None:
        table = _format_matrix(results)
        log.info(f"{test_name} iteration matrix:\n{table}")
        (log_path / f"{test_name}_matrix.md").write_text(table, encoding="utf-8")
        (log_path / f"{test_name}_matrix.json").write_text(
            json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8"
        )

    def _get_disk_img_copy_path(self, node: Node, log: Logger) -> PurePath:
        # The guest disk image is copied once per concurrent VM, so we need
        # a directory backed by a large disk. Prefer an existing resource
        # disk mount, otherwise try to mount an unused nvme*n1 disk at
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
                "No mounted resource disk and no unused nvme*n1 disk found, "
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
