# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, cast

from azure.core.exceptions import (
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.mgmt.compute.models import RunCommandInput
from dateutil.parser import isoparse

from lisa import Environment, Logger, Node
from lisa.sut_orchestrator.azure.common import (
    get_compute_client,
    get_node_context,
    wait_operation,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import LisaException, LisaTimeoutException
from lisa.util.parallel import check_cancelled
from lisa.util.perf_timer import create_timer

_CYCLE_COUNT = 5
_LOAD_FRACTION_STEP = 0.10
_LOAD_FRACTION_MAX = 0.50
_ALLOCATION_TIMEOUT_SECONDS = 900
_HIBERNATE_TIMEOUT_SECONDS = 3000
_RESUME_TIMEOUT_SECONDS = 3000
_STATUS_TIMEOUT_SECONDS = 180
_GUEST_READY_TIMEOUT_SECONDS = 30 * 60
_BOOT_TIME_TOLERANCE_SECONDS = 60
_COMPONENT_STATUS_RESUME_SUCCEEDED = "ComponentStatus/VMBootState/Resume/succeeded"

_MEMORY_STATE_PATTERN = re.compile(
    r"HRMEM:(?P<pid>\d+):(?P<ticks>\d+):" r"(?P<target>\d+):(?P<held>\d+)"
)
_BOOT_TIME_PATTERN = re.compile(r"HRBOOT:(?P<boot>.+?):HRBOOT")
_MARKER_PATTERN = re.compile(r"HRMARKER:(?P<state>ALIVE|DEAD)(?::(?P<ticks>\d+))?")
_SCRIPT_ROOT = Path(__file__).parent.parent / "scripts"
_LINUX_MEMORY_LOADER = _SCRIPT_ROOT / "hibernate_memory_load.py"
_WINDOWS_MEMORY_LOADER = _SCRIPT_ROOT / "hibernate_memory_load.cs"
_WINDOWS_MEMORY_LOADER_PATH = r"C:\Windows\Temp\LoadMemory_HibernateVMBytes.exe"
_TRANSIENT_HTTP_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class _MarkerState:
    pid: int
    start_ticks: int
    service_name: str = ""


@dataclass(frozen=True)
class _MemoryLoadState:
    pid: int
    start_ticks: int
    target_bytes: int
    held_bytes: int


@dataclass(frozen=True)
class _ResumeBaseline:
    boot_time: datetime
    marker: _MarkerState


class HibernateResumeValidator:
    def __init__(
        self,
        node: Node,
        log: Logger,
        environment: Environment,
        extension_name: str,
        is_windows: bool,
    ) -> None:
        if not environment.platform:
            raise LisaException("Azure platform is required.")
        platform = cast(AzurePlatform, environment.platform)
        if not isinstance(platform, AzurePlatform):
            raise LisaException("HibernateResume validation requires AzurePlatform.")

        node_context = get_node_context(node)
        self._environment = environment
        self._log = log
        self._extension_name = extension_name
        self._is_windows = is_windows
        self._compute_client = get_compute_client(platform)
        self._resource_group_name = node_context.resource_group_name
        self._vm_name = node_context.vm_name

    def run(self) -> None:
        self._environment.mark_dirty()
        run_timer = create_timer()
        started_at = datetime.now(timezone.utc)
        baseline: Optional[_ResumeBaseline] = None
        memory_state: Optional[_MemoryLoadState] = None

        self._log.info(
            "Starting hibernate/resume validation: "
            f"vm='{self._vm_name}', resource_group='{self._resource_group_name}', "
            f"extension='{self._extension_name}', "
            f"os={'Windows' if self._is_windows else 'Linux'}, "
            f"started_utc='{started_at.isoformat()}'."
        )
        self._log.info(
            "Hibernate validation configuration: "
            f"cycles={_CYCLE_COUNT}, memory_load_step={_LOAD_FRACTION_STEP:.0%}, "
            f"maximum_memory_load={_LOAD_FRACTION_MAX:.0%}, "
            f"allocation_timeout={_ALLOCATION_TIMEOUT_SECONDS}s, "
            f"hibernate_timeout={_HIBERNATE_TIMEOUT_SECONDS}s, "
            f"resume_timeout={_RESUME_TIMEOUT_SECONDS}s, "
            f"status_timeout={_STATUS_TIMEOUT_SECONDS}s, "
            f"guest_ready_timeout={_GUEST_READY_TIMEOUT_SECONDS}s, "
            f"boot_time_tolerance={_BOOT_TIME_TOLERANCE_SECONDS}s."
        )

        try:
            self._log_vm_configuration()
            self._verify_hibernation_enabled()
            baseline = self._capture_resume_baseline()
            self._log.info(
                "Captured resume continuity baseline: "
                f"boot_time_utc='{baseline.boot_time.isoformat()}', "
                f"marker_pid={baseline.marker.pid}, "
                f"marker_start_ticks={baseline.marker.start_ticks}, "
                f"marker_service='{baseline.marker.service_name or 'process'}'."
            )
            for cycle in range(1, _CYCLE_COUNT + 1):
                cycle_timer = create_timer()
                cycle_started_at = datetime.now(timezone.utc)
                fraction = min(
                    cycle * _LOAD_FRACTION_STEP,
                    _LOAD_FRACTION_MAX,
                )
                self._log.info(
                    f"Starting hibernate/resume cycle {cycle}/{_CYCLE_COUNT} "
                    f"with {fraction:.0%} of available guest memory at "
                    f"{cycle_started_at.isoformat()}."
                )
                allocation_timer = create_timer()
                memory_state = self._start_memory_load(
                    load_fraction=fraction,
                    previous_state=memory_state,
                )
                allocation_elapsed = allocation_timer.elapsed()
                self._log.info(
                    f"Cycle {cycle}/{_CYCLE_COUNT} memory load is ready: "
                    f"pid={memory_state.pid}, "
                    f"start_ticks={memory_state.start_ticks}, "
                    f"target={self._format_bytes(memory_state.target_bytes)}, "
                    f"held={self._format_bytes(memory_state.held_bytes)}, "
                    f"requested_fraction={fraction:.0%}, "
                    f"allocation_elapsed={allocation_elapsed:.2f}s."
                )
                previous_extension_status_time: Optional[datetime] = None
                if self._is_windows:
                    previous_extension_status_time = (
                        self._wait_for_windows_extension_status_time()
                    )
                hibernate_phase_timer = create_timer()
                self._hibernate()
                self._wait_for_vm_status(
                    code_prefix="HibernationState",
                    expected_display_status="VM hibernated",
                )
                hibernate_phase_elapsed = hibernate_phase_timer.elapsed()
                self._log.info(
                    f"Cycle {cycle}/{_CYCLE_COUNT} hibernate phase completed in "
                    f"{hibernate_phase_elapsed:.2f}s."
                )
                resume_phase_timer = create_timer()
                self._resume()
                self._wait_for_vm_status(
                    code_prefix="PowerState",
                    expected_display_status="VM running",
                )
                self._wait_for_guest_agent_ready()
                if self._is_windows:
                    if previous_extension_status_time is None:
                        raise LisaException(
                            "Windows extension status baseline was not captured."
                        )
                    self._validate_windows_resume_substatus(
                        previous_status_time=previous_extension_status_time
                    )
                resume_phase_elapsed = resume_phase_timer.elapsed()
                self._log.info(
                    f"Cycle {cycle}/{_CYCLE_COUNT} resume phase completed in "
                    f"{resume_phase_elapsed:.2f}s."
                )
                self._validate_resume_not_reboot(baseline)
                self._validate_memory_load(memory_state)
                cycle_elapsed = cycle_timer.elapsed()
                self._log.info(
                    f"Hibernate/resume cycle {cycle}/{_CYCLE_COUNT} succeeded in "
                    f"{cycle_elapsed:.2f}s; completed_utc="
                    f"'{datetime.now(timezone.utc).isoformat()}'."
                )

            wait_seconds = random.randint(60, 120)
            self._log.info(f"Waiting {wait_seconds} seconds after the final resume.")
            time.sleep(wait_seconds)
        except Exception as error:
            self._log.error(
                "Hibernate/resume validation failed after "
                f"{run_timer.elapsed():.2f}s: {error}"
            )
            raise
        finally:
            cleanup_timer = create_timer()
            self._ensure_vm_running_for_cleanup()
            if baseline:
                self._cleanup_processes(memory_state, baseline.marker)
            self._log.info(
                "Hibernate/resume validation cleanup phase finished; "
                f"cleanup_elapsed={cleanup_timer.elapsed():.2f}s, "
                f"total_elapsed={run_timer.elapsed():.2f}s, "
                f"finished_utc='{datetime.now(timezone.utc).isoformat()}'."
            )

    def _verify_hibernation_enabled(self) -> None:
        vm = self._get_vm(expand_instance_view=False)
        additional_capabilities = getattr(vm, "additional_capabilities", None)
        enabled = getattr(
            additional_capabilities,
            "hibernation_enabled",
            False,
        )
        if str(enabled).casefold() != "true":
            raise LisaException(
                f"VM '{self._vm_name}' does not report "
                "additionalCapabilities.hibernationEnabled=true."
            )
        self._log.info(f"Verified Azure VM '{self._vm_name}' has hibernation enabled.")

    def _get_vm(self, expand_instance_view: bool = True) -> Any:
        return self._compute_client.virtual_machines.get(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
            expand="instanceView" if expand_instance_view else None,
        )

    def _log_vm_configuration(self) -> None:
        try:
            vm = self._get_vm(expand_instance_view=False)
            hardware_profile = getattr(vm, "hardware_profile", None)
            storage_profile = getattr(vm, "storage_profile", None)
            image_reference = getattr(storage_profile, "image_reference", None)
            os_disk = getattr(storage_profile, "os_disk", None)
            managed_disk = getattr(os_disk, "managed_disk", None)
            additional_capabilities = getattr(vm, "additional_capabilities", None)
            security_profile = getattr(vm, "security_profile", None)
            uefi_settings = getattr(security_profile, "uefi_settings", None)

            image = ":".join(
                str(getattr(image_reference, field, "") or "unknown")
                for field in ("publisher", "offer", "sku", "version")
            )
            os_type = getattr(os_disk, "os_type", None)
            os_type = getattr(os_type, "value", os_type)
            disk_caching = getattr(os_disk, "caching", None)
            disk_caching = getattr(disk_caching, "value", disk_caching)
            storage_type = getattr(managed_disk, "storage_account_type", None)
            storage_type = getattr(storage_type, "value", storage_type)
            security_type = getattr(security_profile, "security_type", None)
            security_type = getattr(security_type, "value", security_type)

            self._log.info(
                "Azure VM configuration: "
                f"name='{getattr(vm, 'name', self._vm_name)}', "
                f"location='{getattr(vm, 'location', 'unknown')}', "
                f"size='{getattr(hardware_profile, 'vm_size', 'unknown')}', "
                f"image='{image}', "
                f"os_type='{os_type or 'unknown'}', "
                f"os_disk_size_gb="
                f"{getattr(os_disk, 'disk_size_gb', 'unknown')}, "
                f"os_disk_name='{getattr(os_disk, 'name', 'unknown')}', "
                f"os_disk_caching='{disk_caching or 'unknown'}', "
                f"os_disk_storage_type='{storage_type or 'unknown'}', "
                f"hibernation_enabled="
                f"{getattr(additional_capabilities, 'hibernation_enabled', False)}, "
                f"zones={getattr(vm, 'zones', None) or []}, "
                f"security_type='{security_type or 'standard'}', "
                f"secure_boot_enabled="
                f"{getattr(uefi_settings, 'secure_boot_enabled', False)}, "
                f"v_tpm_enabled="
                f"{getattr(uefi_settings, 'v_tpm_enabled', False)}, "
                "architecture_requirement='x64'."
            )
        except Exception as error:
            self._log.warning(
                f"Could not collect Azure VM configuration for logging: {error}"
            )

    def _capture_resume_baseline(self) -> _ResumeBaseline:
        if self._is_windows:
            script = r"""
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$computer = Get-CimInstance -ClassName Win32_ComputerSystem
$boot = $os.LastBootUpTime
$payload = 'while ($true) { Start-Sleep -Seconds 3600 }'
$encoded = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($payload))
$commandLine = 'powershell.exe -NoProfile -NonInteractive ' +
    '-WindowStyle Hidden -EncodedCommand ' + $encoded
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
    -Arguments @{ CommandLine = $commandLine }
if ($result.ReturnValue -ne 0) {
    throw "Win32_Process.Create failed with $($result.ReturnValue)."
}
$process = Get-Process -Id $result.ProcessId -ErrorAction Stop
Write-Output "HRCONFIG:os=$($os.Caption)"
Write-Output "HRCONFIG:os_version=$($os.Version)"
Write-Output "HRCONFIG:os_build=$($os.BuildNumber)"
Write-Output "HRCONFIG:architecture=$env:PROCESSOR_ARCHITECTURE"
Write-Output "HRCONFIG:logical_processors=$($computer.NumberOfLogicalProcessors)"
Write-Output "HRCONFIG:total_memory_bytes=$($computer.TotalPhysicalMemory)"
Write-Output "HRCONFIG:available_memory_bytes=$([long]$os.FreePhysicalMemory * 1024L)"
Write-Output "HRBOOT:$($boot.ToUniversalTime().ToString('o')):HRBOOT"
Write-Output "HRPID:$($result.ProcessId):$($process.StartTime.Ticks)"
"""
        else:
            script = """
set -eu
service=lisa-hr-resume-marker
systemctl stop "$service" >/dev/null 2>&1 || true
systemctl reset-failed "$service" >/dev/null 2>&1 || true
systemd-run --unit="$service" --collect --property=Type=simple \
    /bin/sleep 100000 >/dev/null
pid=$(systemctl show --property=MainPID --value "$service")
[ "$pid" -gt 1 ]
ticks=$(sed 's/.*) //' "/proc/$pid/stat" | awk '{print $20}')
boot=$(uptime -s)
. /etc/os-release
total_kb=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
available_kb=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
printf 'HRCONFIG:os=%s\n' "${PRETTY_NAME:-unknown}"
printf 'HRCONFIG:kernel=%s\n' "$(uname -r)"
printf 'HRCONFIG:architecture=%s\n' "$(uname -m)"
printf 'HRCONFIG:logical_processors=%s\n' "$(getconf _NPROCESSORS_ONLN)"
printf 'HRCONFIG:total_memory_bytes=%s\n' "$((total_kb * 1024))"
printf 'HRCONFIG:available_memory_bytes=%s\n' "$((available_kb * 1024))"
printf 'HRBOOT:%s:HRBOOT\n' "$boot"
printf 'HRPID:%s:%s\n' "$pid" "$ticks"
"""
        output = self._run_guest_command(script)
        guest_configuration: List[str] = []
        for line in output.splitlines():
            if not line.startswith("HRCONFIG:"):
                continue
            name, separator, value = line[len("HRCONFIG:") :].partition("=")
            if separator and name.endswith("_memory_bytes") and value.isdigit():
                guest_configuration.append(f"{name}={self._format_bytes(int(value))}")
            else:
                guest_configuration.append(line[len("HRCONFIG:") :])
        if guest_configuration:
            self._log.info("Guest configuration: " + ", ".join(guest_configuration))
        boot_time = self._parse_boot_time(output)
        matched = re.search(r"HRPID:(?P<pid>\d+):(?P<ticks>\d+)", output)
        if not matched:
            raise LisaException(f"Cannot determine marker process id from '{output}'.")
        marker_pid = int(matched.group("pid"))
        marker_ticks = int(matched.group("ticks"))
        if marker_pid <= 1 or marker_ticks <= 0:
            raise LisaException(
                f"Invalid marker process identity '{marker_pid}:{marker_ticks}'."
            )
        return _ResumeBaseline(
            boot_time=boot_time,
            marker=_MarkerState(
                pid=marker_pid,
                start_ticks=marker_ticks,
                service_name="" if self._is_windows else "lisa-hr-resume-marker",
            ),
        )

    def _hibernate(self) -> None:
        self._run_vm_operation(
            lambda: self._compute_client.virtual_machines.begin_deallocate(
                resource_group_name=self._resource_group_name,
                vm_name=self._vm_name,
                hibernate=True,
            ),
            "hibernate",
            _HIBERNATE_TIMEOUT_SECONDS,
        )

    def _resume(self) -> None:
        self._run_vm_operation(
            lambda: self._compute_client.virtual_machines.begin_start(
                resource_group_name=self._resource_group_name,
                vm_name=self._vm_name,
            ),
            "resume",
            _RESUME_TIMEOUT_SECONDS,
        )

    def _run_vm_operation(
        self,
        operation_factory: Callable[[], Any],
        operation_name: str,
        timeout: int,
    ) -> None:
        for attempt in range(1, 7):
            check_cancelled()
            timer = create_timer()
            try:
                self._log.info(
                    f"Submitting Azure VM {operation_name} operation "
                    f"(attempt {attempt}/6) at "
                    f"{datetime.now(timezone.utc).isoformat()}."
                )
                operation = operation_factory()
                wait_operation(
                    operation,
                    time_out=timeout,
                    failure_identity=operation_name,
                )
                elapsed = timer.elapsed()
                if elapsed >= timeout:
                    raise LisaException(
                        f"{operation_name.capitalize()} operation exceeded "
                        f"{timeout} seconds: {elapsed:.2f}."
                    )
                self._log.info(
                    f"Azure VM {operation_name} operation completed on "
                    f"attempt {attempt}/6 in {elapsed:.2f}s."
                )
                return
            except Exception as error:
                check_cancelled()
                if attempt == 6 or not self._is_transient_vm_operation_error(error):
                    raise
                self._log.info(
                    f"Retrying {operation_name} operation after attempt "
                    f"{attempt}/6 failed: {error}"
                )
                time.sleep(10)

    @staticmethod
    def _is_transient_vm_operation_error(error: Exception) -> bool:
        if isinstance(
            error,
            (LisaTimeoutException, ServiceRequestError, ServiceResponseError),
        ):
            return True
        if isinstance(error, HttpResponseError):
            return getattr(error, "status_code", None) in _TRANSIENT_HTTP_STATUS_CODES
        return False

    def _wait_for_vm_status(
        self,
        code_prefix: str,
        expected_display_status: str,
    ) -> None:
        timer = create_timer()
        last_statuses = ""
        previous_statuses = ""
        while timer.elapsed(False) < _STATUS_TIMEOUT_SECONDS:
            vm = self._get_vm()
            instance_view = getattr(vm, "instance_view", None)
            statuses = getattr(instance_view, "statuses", None) or []
            last_statuses = ", ".join(
                f"{getattr(status, 'code', '')}:"
                f"{getattr(status, 'display_status', '')}"
                for status in statuses
            )
            if last_statuses != previous_statuses:
                self._log.info(
                    f"Waiting for VM status '{expected_display_status}'; "
                    f"observed=[{last_statuses}], elapsed={timer.elapsed():.2f}s."
                )
                previous_statuses = last_statuses
            for status in statuses:
                code = str(getattr(status, "code", ""))
                display_status = str(getattr(status, "display_status", ""))
                if code.casefold().startswith(code_prefix.casefold()) and (
                    expected_display_status.casefold() in display_status.casefold()
                ):
                    self._log.info(
                        f"VM status reached '{code}:{display_status}' after "
                        f"{timer.elapsed():.2f}s."
                    )
                    return
            time.sleep(10)

        raise LisaException(
            f"VM '{self._vm_name}' did not reach status "
            f"'{code_prefix}*/{expected_display_status}' within "
            f"{_STATUS_TIMEOUT_SECONDS} seconds. Last statuses: {last_statuses}"
        )

    def _wait_for_guest_agent_ready(self) -> None:
        timer = create_timer()
        last_status = ""
        previous_status = ""
        while timer.elapsed(False) < _GUEST_READY_TIMEOUT_SECONDS:
            vm = self._get_vm()
            instance_view = getattr(vm, "instance_view", None)
            vm_agent = getattr(instance_view, "vm_agent", None)
            statuses = getattr(vm_agent, "statuses", None) or []
            if statuses:
                last_status = str(getattr(statuses[0], "display_status", ""))
                if last_status != previous_status:
                    self._log.info(
                        "Waiting for guest agent Ready; "
                        f"observed='{last_status}', elapsed={timer.elapsed():.2f}s."
                    )
                    previous_status = last_status
                if last_status.casefold() == "ready":
                    self._log.info(
                        f"Guest agent reported Ready after " f"{timer.elapsed():.2f}s."
                    )
                    return
            time.sleep(10)

        raise LisaException(
            f"Guest agent on '{self._vm_name}' did not report Ready within "
            f"{_GUEST_READY_TIMEOUT_SECONDS // 60} minutes. "
            f"Last status: '{last_status}'."
        )

    def _get_latest_windows_extension_status_time(self) -> Optional[datetime]:
        vm = self._get_vm()
        instance_view = getattr(vm, "instance_view", None)
        extensions = getattr(instance_view, "extensions", None) or []
        extension = next(
            (
                candidate
                for candidate in extensions
                if str(getattr(candidate, "name", "")).casefold()
                == self._extension_name.casefold()
            ),
            None,
        )
        if extension is None:
            return None

        status_times = [
            status_time
            for status in (getattr(extension, "statuses", None) or [])
            if str(getattr(status, "code", "")).casefold()
            == "provisioningstate/succeeded"
            for status_time in [self._parse_status_time(getattr(status, "time", None))]
            if status_time is not None
        ]
        return max(status_times) if status_times else None

    def _wait_for_windows_extension_status_time(self) -> datetime:
        timer = create_timer()
        while timer.elapsed(False) < _STATUS_TIMEOUT_SECONDS:
            status_time = self._get_latest_windows_extension_status_time()
            if status_time is not None:
                self._log.info(
                    "Captured Windows extension status baseline immediately "
                    f"before hibernate: extension='{self._extension_name}', "
                    f"status_time_utc='{status_time.isoformat()}', "
                    f"elapsed={timer.elapsed():.2f}s."
                )
                return status_time
            time.sleep(10)

        raise LisaException(
            f"Windows hibernate extension '{self._extension_name}' did not "
            f"report a timestamped successful provisioning status within "
            f"{_STATUS_TIMEOUT_SECONDS} seconds."
        )

    def _validate_windows_resume_substatus(
        self,
        previous_status_time: datetime,
    ) -> datetime:
        timer = create_timer()
        last_codes: List[str] = []
        last_extension_statuses: List[str] = []
        last_status_times: List[datetime] = []
        while timer.elapsed(False) < _STATUS_TIMEOUT_SECONDS:
            vm = self._get_vm()
            instance_view = getattr(vm, "instance_view", None)
            extensions = getattr(instance_view, "extensions", None) or []
            extension = next(
                (
                    candidate
                    for candidate in extensions
                    if str(getattr(candidate, "name", "")).casefold()
                    == self._extension_name.casefold()
                ),
                None,
            )
            if extension is not None:
                extension_statuses = getattr(extension, "statuses", None) or []
                last_extension_statuses = [
                    str(getattr(status, "code", "")) for status in extension_statuses
                ]
                provisioning_succeeded = any(
                    code.casefold() == "provisioningstate/succeeded"
                    for code in last_extension_statuses
                )
                last_status_times = [
                    status_time
                    for status in extension_statuses
                    for status_time in [
                        self._parse_status_time(getattr(status, "time", None))
                    ]
                    if status_time is not None
                ]
                substatuses = getattr(extension, "substatuses", None) or []
                last_codes = [
                    str(getattr(status, "code", "")) for status in substatuses
                ]
                resume_succeeded = any(
                    code.casefold() == _COMPONENT_STATUS_RESUME_SUCCEEDED.casefold()
                    for code in last_codes
                )
                fresh_status_times = [
                    status_time
                    for status_time in last_status_times
                    if status_time > previous_status_time
                ]
                if provisioning_succeeded and resume_succeeded and fresh_status_times:
                    current_status_time = max(fresh_status_times)
                    self._log.info(
                        "Validated Windows guest resume status: "
                        f"substatus='{_COMPONENT_STATUS_RESUME_SUCCEEDED}', "
                        f"previous_status_time_utc="
                        f"'{previous_status_time.isoformat()}', "
                        f"current_status_time_utc="
                        f"'{current_status_time.isoformat()}', "
                        f"extension_statuses={last_extension_statuses}, "
                        f"elapsed={timer.elapsed():.2f}s."
                    )
                    return current_status_time
            time.sleep(10)

        raise LisaException(
            f"Windows hibernate extension '{self._extension_name}' did not "
            f"report a fresh '{_COMPONENT_STATUS_RESUME_SUCCEEDED}' while "
            f"provisioning was succeeded within {_STATUS_TIMEOUT_SECONDS} seconds. "
            f"Extension statuses: {last_extension_statuses}; substatus codes: "
            f"{last_codes}; extension status times: {last_status_times}; previous "
            f"extension status time: {previous_status_time}."
        )

    def _validate_resume_not_reboot(self, baseline: _ResumeBaseline) -> None:
        if self._is_windows:
            script = f"""
$boot = (Get-CimInstance -ClassName Win32_OperatingSystem).LastBootUpTime
$process = Get-Process -Id {baseline.marker.pid} -ErrorAction SilentlyContinue
Write-Output "HRBOOT:$($boot.ToUniversalTime().ToString('o')):HRBOOT"
if ($null -eq $process) {{
    Write-Output 'HRMARKER:DEAD'
}} else {{
    Write-Output "HRMARKER:ALIVE:$($process.StartTime.Ticks)"
}}
"""
        else:
            script = f"""
set -eu
boot=$(uptime -s)
printf 'HRBOOT:%s:HRBOOT\n' "$boot"
if kill -0 {baseline.marker.pid} 2>/dev/null; then
    ticks=$(sed 's/.*) //' "/proc/{baseline.marker.pid}/stat" | awk '{{print $20}}')
    echo "HRMARKER:ALIVE:$ticks"
else
    echo HRMARKER:DEAD
fi
"""
        output = self._run_guest_command(script)
        current_boot_time = self._parse_boot_time(output)
        boot_delta_seconds = abs(
            current_boot_time.timestamp() - baseline.boot_time.timestamp()
        )
        if boot_delta_seconds > _BOOT_TIME_TOLERANCE_SECONDS:
            raise LisaException(
                f"Guest boot time changed by {boot_delta_seconds:.2f} seconds "
                "after resume; the VM rebooted instead of resuming."
            )
        marker_match = _MARKER_PATTERN.search(output)
        if (
            not marker_match
            or marker_match.group("state") != "ALIVE"
            or int(marker_match.group("ticks") or 0) != baseline.marker.start_ticks
        ):
            raise LisaException(
                f"Marker process {baseline.marker.pid} did not survive resume."
            )
        self._log.info(
            "Validated resume continuity: "
            f"baseline_boot_time_utc='{baseline.boot_time.isoformat()}', "
            f"current_boot_time_utc='{current_boot_time.isoformat()}', "
            f"boot_time_delta={boot_delta_seconds:.2f}s, "
            f"marker_pid={baseline.marker.pid}, "
            f"marker_start_ticks={baseline.marker.start_ticks}, "
            "marker_state='ALIVE'."
        )

    def _start_memory_load(
        self,
        load_fraction: float,
        previous_state: Optional[_MemoryLoadState],
    ) -> _MemoryLoadState:
        if self._is_windows:
            return self._start_windows_memory_load(
                load_fraction,
                previous_state,
            )
        return self._start_linux_memory_load(
            load_fraction,
            previous_state,
        )

    def _start_linux_memory_load(
        self,
        load_fraction: float,
        previous_state: Optional[_MemoryLoadState],
    ) -> _MemoryLoadState:
        script_path = "/var/tmp/hr_memload.py"
        ready_path = "/var/tmp/hr_memload.ready"
        service_name = "lisa-hr-memory-loader"
        source = self._encode_asset(_LINUX_MEMORY_LOADER)
        previous_check = ""
        if previous_state:
            previous_check = f"""
old_pid={previous_state.pid}
if [ -d "/proc/$old_pid" ]; then
    old_ticks=$(sed 's/.*) //' "/proc/$old_pid/stat" | awk '{{print $20}}')
    [ "$old_ticks" = "{previous_state.start_ticks}" ]
fi
"""
        command = f"""
set -eu
script={script_path}
ready={ready_path}
service={service_name}
printf '%s' '{source}' | base64 --decode > "$script"
chmod 700 "$script"
{previous_check}
systemctl stop "$service" >/dev/null 2>&1 || true
systemctl reset-failed "$service" >/dev/null 2>&1 || true
rm -f "$ready"
python_bin=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
[ -n "$python_bin" ]
available_kb=$(awk '/^MemAvailable:/{{print $2}}' /proc/meminfo)
target=$(awk -v available="$available_kb" -v fraction="{load_fraction}" \
    'BEGIN {{ printf "%.0f", int(available * 1024 * fraction) }}')
[ "$target" -gt 0 ]
systemd-run --unit="$service" --collect --property=Type=simple \
    --property=Restart=no "$python_bin" "$script" "$target" "$ready" >/dev/null
pid=$(systemctl show --property=MainPID --value "$service")
[ "$pid" -gt 1 ]
ticks=$(sed 's/.*) //' "/proc/$pid/stat" | awk '{{print $20}}')
threshold=$(awk -v target="$target" 'BEGIN {{ printf "%.0f", target * 0.90 }}')
deadline=$(( $(date +%s) + {_ALLOCATION_TIMEOUT_SECONDS} ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    sleep 15
    [ -d "/proc/$pid" ] || {{
        journalctl -u "$service" -n 20 --no-pager
        exit 1
    }}
    rss_kb=$(awk '/^VmRSS:/{{print $2}}' "/proc/$pid/status")
    held=$((rss_kb * 1024))
    if [ -f "$ready" ] && [ "$(cat "$ready")" = "$target" ] &&
       [ "$held" -ge "$threshold" ]; then
        echo "HRMEM:$pid:$ticks:$target:$held"
        exit 0
    fi
done
systemctl stop "$service" >/dev/null 2>&1 || true
exit 1
"""
        output = self._run_guest_command(
            command,
            timeout=_ALLOCATION_TIMEOUT_SECONDS + 120,
        )
        return self._parse_memory_state(output)

    def _start_windows_memory_load(
        self,
        load_fraction: float,
        previous_state: Optional[_MemoryLoadState],
    ) -> _MemoryLoadState:
        source_path = r"C:\Windows\Temp\hibernate_memory_load.cs"
        executable_path = _WINDOWS_MEMORY_LOADER_PATH
        ready_path = f"{executable_path}.ready"
        source = self._encode_asset(_WINDOWS_MEMORY_LOADER)
        previous_check = ""
        reset_executable = ""
        if previous_state:
            previous_check = f"""
$oldProcess = Get-Process -Id {previous_state.pid} -ErrorAction SilentlyContinue
if ($null -ne $oldProcess) {{
    if ($oldProcess.StartTime.Ticks -ne {previous_state.start_ticks}) {{
        throw 'Memory-loader process id was reused.'
    }}
    Stop-Process -Id $oldProcess.Id -Force
    Wait-Process -Id $oldProcess.Id -Timeout 30 -ErrorAction SilentlyContinue
}}
"""
        else:
            reset_executable = (
                "Remove-Item -LiteralPath $executablePath -Force "
                "-ErrorAction SilentlyContinue"
            )
        command = f"""
$ErrorActionPreference = 'Stop'
$sourcePath = '{source_path}'
$executablePath = '{executable_path}'
$ready = '{ready_path}'
[IO.File]::WriteAllBytes(
    $sourcePath,
    [Convert]::FromBase64String('{source}'))
{reset_executable}
if (-not (Test-Path -LiteralPath $executablePath)) {{
    $sourceCode = Get-Content -LiteralPath $sourcePath -Raw
    try {{
        Add-Type -TypeDefinition $sourceCode -OutputAssembly $executablePath `
            -OutputType ConsoleApplication -ErrorAction Stop
    }}
    catch {{
        $compiler = Get-ChildItem `
            -Path "$env:WINDIR\\Microsoft.NET\\Framework64" `
            -Filter 'csc.exe' -Recurse |
            Sort-Object -Property FullName -Descending |
            Select-Object -First 1
        if ($null -eq $compiler) {{ throw }}
        & $compiler.FullName /nologo /optimize+ /platform:x64 /target:exe `
            /out:$executablePath $sourcePath | Out-Null
        if ($LASTEXITCODE -ne 0) {{ throw 'csc.exe compilation failed.' }}
    }}
}}
{previous_check}
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$availableBytes = [long]$os.FreePhysicalMemory * 1024L
$totalBytes = [long]$os.TotalVisibleMemorySize * 1024L
if ($availableBytes -le 0 -or $availableBytes -gt $totalBytes) {{
    throw 'Cannot determine available physical memory.'
}}
$target = [long][Math]::Floor($availableBytes * {load_fraction})
if ($target -le 0) {{ throw 'Requested memory load rounds to zero bytes.' }}
Remove-Item -LiteralPath $ready -Force -ErrorAction SilentlyContinue
$commandLine = '"' + $executablePath + '" ' + $target + ' 100 "' + $ready + '"'
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
    -Arguments @{{ CommandLine = $commandLine }}
if ($created.ReturnValue -ne 0) {{
    throw "Win32_Process.Create failed with $($created.ReturnValue)."
}}
$process = Get-Process -Id $created.ProcessId -ErrorAction Stop
try {{
    $process.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
}} catch {{}}
$deadline = (Get-Date).AddSeconds({_ALLOCATION_TIMEOUT_SECONDS})
while ((Get-Date) -lt $deadline) {{
    Start-Sleep -Seconds 15
    $process.Refresh()
    if ($process.HasExited) {{ throw 'Memory loader exited during allocation.' }}
    $readyBytes = 0L
    $isReady = (Test-Path -LiteralPath $ready) -and
        [long]::TryParse(
            (Get-Content -LiteralPath $ready -Raw),
            [ref]$readyBytes)
    if ($isReady -and $readyBytes -eq $target -and
        $process.PrivateMemorySize64 -ge ($target * 0.90)) {{
        Write-Output (
            "HRMEM:$($process.Id):$($process.StartTime.Ticks):" +
            "${{target}}:$($process.PrivateMemorySize64)")
        exit 0
    }}
}}
Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
throw 'Memory loader did not reach its target before timeout.'
"""
        output = self._run_guest_command(
            command,
            timeout=_ALLOCATION_TIMEOUT_SECONDS + 120,
        )
        return self._parse_memory_state(output)

    def _validate_memory_load(self, state: _MemoryLoadState) -> None:
        if self._is_windows:
            command = f"""
$process = Get-Process -Id {state.pid} -ErrorAction SilentlyContinue
if ($null -eq $process) {{ Write-Output 'MISSING'; exit 0 }}
if ($process.StartTime.Ticks -ne {state.start_ticks}) {{
    Write-Output 'REPLACED'
    exit 0
}}
$process.Refresh()
Write-Output (
    "HRMEM:$($process.Id):$($process.StartTime.Ticks):" +
    "{state.target_bytes}:$($process.PrivateMemorySize64)")
"""
        else:
            command = f"""
set -eu
pid={state.pid}
[ -d "/proc/$pid" ] || {{ echo MISSING; exit 0; }}
ticks=$(sed 's/.*) //' "/proc/$pid/stat" | awk '{{print $20}}')
[ "$ticks" = "{state.start_ticks}" ] || {{ echo REPLACED; exit 0; }}
main_pid=$(systemctl show --property=MainPID --value lisa-hr-memory-loader)
[ "$main_pid" = "$pid" ] || {{ echo REPLACED; exit 0; }}
rss_kb=$(awk '/^VmRSS:/{{print $2}}' "/proc/$pid/status")
echo "HRMEM:$pid:$ticks:{state.target_bytes}:$((rss_kb * 1024))"
"""
        output = self._run_guest_command(command)
        if "MISSING" in output:
            raise LisaException(
                f"Memory-load process {state.pid} did not survive resume."
            )
        if "REPLACED" in output:
            raise LisaException(
                f"Memory-load process id {state.pid} was reused after resume."
            )
        current_state = self._parse_memory_state(
            output,
            require_target_threshold=False,
        )
        if current_state.held_bytes <= 0:
            raise LisaException(
                f"Memory-load process {state.pid} reports no resident memory."
            )
        self._log.info(
            "Validated memory-load continuity: "
            f"pid={state.pid}, start_ticks={state.start_ticks}, "
            f"target={self._format_bytes(state.target_bytes)}, "
            f"pre_hibernate_held={self._format_bytes(state.held_bytes)}, "
            f"post_resume_held={self._format_bytes(current_state.held_bytes)}, "
            f"post_resume_target_ratio="
            f"{current_state.held_bytes / state.target_bytes:.2%}."
        )

    def _parse_memory_state(
        self,
        output: str,
        require_target_threshold: bool = True,
    ) -> _MemoryLoadState:
        matched = _MEMORY_STATE_PATTERN.search(output)
        if not matched:
            raise LisaException(f"Cannot parse memory-load state from output: {output}")
        state = _MemoryLoadState(
            pid=int(matched.group("pid")),
            start_ticks=int(matched.group("ticks")),
            target_bytes=int(matched.group("target")),
            held_bytes=int(matched.group("held")),
        )
        if (
            state.pid <= 1
            or state.start_ticks <= 0
            or state.target_bytes <= 0
            or (
                require_target_threshold
                and state.held_bytes < state.target_bytes * 0.90
            )
        ):
            raise LisaException(f"Invalid memory-load state: {state}")
        return state

    def _parse_boot_time(self, output: str) -> datetime:
        matched = _BOOT_TIME_PATTERN.search(output)
        if not matched:
            raise LisaException(f"Cannot parse boot time from output: {output}")
        try:
            return cast(datetime, isoparse(matched.group("boot").strip()))
        except ValueError as error:
            raise LisaException(
                f"Cannot parse boot time '{matched.group('boot')}'."
            ) from error

    @staticmethod
    def _format_bytes(value: int) -> str:
        return f"{value} bytes ({value / 1024 / 1024:.2f} MiB)"

    @staticmethod
    def _parse_status_time(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            try:
                parsed = cast(datetime, isoparse(value.strip()))
            except ValueError:
                return None
        else:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _run_guest_command(self, script: str, timeout: int = 15 * 60) -> str:
        timer = create_timer()
        command_name = "RunPowerShellScript" if self._is_windows else "RunShellScript"
        self._log.info(
            f"Submitting guest {command_name} at "
            f"{datetime.now(timezone.utc).isoformat()} with timeout={timeout}s."
        )
        command = RunCommandInput(
            command_id=command_name,
            script=[script],
        )
        operation = self._compute_client.virtual_machines.begin_run_command(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
            parameters=command,
        )
        result = wait_operation(
            operation,
            time_out=timeout,
            failure_identity="guest run command",
        )
        messages = [
            str(value.get("message", ""))
            for value in (result or {}).get("value", [])
            if isinstance(value, dict)
        ]
        failures = [
            str(value.get("message", "") or value.get("code", ""))
            for value in (result or {}).get("value", [])
            if isinstance(value, dict)
            and (
                str(value.get("code", "")).casefold().endswith("/failed")
                or str(value.get("level", "")).casefold() == "error"
            )
        ]
        output = "\n".join(message for message in messages if message)
        self._log.debug(f"Guest run-command output: {output}")
        if failures:
            raise LisaException(
                "Guest run command reported failure: " + "\n".join(failures)
            )
        self._log.info(
            f"Guest {command_name} completed in {timer.elapsed():.2f}s with "
            f"{len(output.splitlines())} output line(s)."
        )
        return output

    @staticmethod
    def _encode_asset(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("ascii")

    def _ensure_vm_running_for_cleanup(self) -> None:
        try:
            vm = self._get_vm()
            instance_view = getattr(vm, "instance_view", None)
            statuses = getattr(instance_view, "statuses", None) or []
            is_running = any(
                str(getattr(status, "code", "")).casefold() == "powerstate/running"
                for status in statuses
            )
            if not is_running:
                self._log.info(
                    "VM is not running during cleanup; resuming it before "
                    "guest-process cleanup."
                )
                self._resume()
                self._wait_for_vm_status("PowerState", "VM running")
                self._wait_for_guest_agent_ready()
            else:
                self._log.info("VM is running and ready for guest-process cleanup.")
        except Exception as error:
            self._log.warning(f"Could not prepare VM for guest cleanup: {error}")

    def _cleanup_processes(
        self,
        memory_state: Optional[_MemoryLoadState],
        marker: _MarkerState,
    ) -> None:
        try:
            if self._is_windows:
                memory_cleanup = ""
                if memory_state:
                    memory_cleanup = f"""
$memoryProcess = Get-Process -Id {memory_state.pid} `
    -ErrorAction SilentlyContinue
if ($null -ne $memoryProcess -and
    $memoryProcess.StartTime.Ticks -eq {memory_state.start_ticks}) {{
    Stop-Process -Id $memoryProcess.Id -Force
}}
"""
                self._run_guest_command(
                    f"""
{memory_cleanup}
$loaderPath = '{_WINDOWS_MEMORY_LOADER_PATH}'
$loaderProcesses = Get-CimInstance -ClassName Win32_Process `
    -Filter "Name = 'LoadMemory_HibernateVMBytes.exe'" `
    -ErrorAction SilentlyContinue
foreach ($loaderProcess in $loaderProcesses) {{
    if ($loaderProcess.ExecutablePath -ieq $loaderPath) {{
        Stop-Process -Id $loaderProcess.ProcessId -Force `
            -ErrorAction SilentlyContinue
    }}
}}
$markerProcess = Get-Process -Id {marker.pid} -ErrorAction SilentlyContinue
if ($null -ne $markerProcess -and
    $markerProcess.StartTime.Ticks -eq {marker.start_ticks}) {{
    Stop-Process -Id $markerProcess.Id -Force
}}
"""
                )
                self._log.info(
                    "Windows guest-process cleanup completed for the memory "
                    f"loader executable and marker pid {marker.pid}."
                )
            else:
                self._run_guest_command(
                    f"""
systemctl stop lisa-hr-memory-loader >/dev/null 2>&1 || true
systemctl reset-failed lisa-hr-memory-loader >/dev/null 2>&1 || true
systemctl stop {marker.service_name} >/dev/null 2>&1 || true
systemctl reset-failed {marker.service_name} >/dev/null 2>&1 || true
"""
                )
                self._log.info(
                    "Linux guest-process cleanup completed for the memory "
                    f"loader and marker service '{marker.service_name}'."
                )
        except Exception as error:
            self._log.warning(f"Guest-process cleanup failed: {error}")
