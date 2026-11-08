# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import time
import xml.etree.ElementTree as ETree
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Type

import redfish
from assertpy import assert_that
from redfish.rest.v1 import JsonDecodingError, RetriesExhaustedError
from retry import retry

from lisa import features, schema
from lisa.environment import Environment
from lisa.util import LisaException, check_till_timeout
from lisa.util.perf_timer import create_timer

from ..platform_ import BareMetalPlatform
from ..schema import ClientSchema, ClusterSchema, IdracClientSchema, IdracSchema
from .cluster import Cluster

# Timeout constants for iDRAC operations (in seconds)
VIRTUAL_MEDIA_EJECT_TIMEOUT = 30
IDRAC_RESET_TIMEOUT = 120
IDRAC_REMOTE_SERVICES_TIMEOUT = 300
VIRTUAL_MEDIA_INSERTION_POLL_TIMEOUT = 30
IDRAC_JOB_QUEUE_TIMEOUT = 300
IDRAC_JOB_QUEUE_POLL_INTERVAL = 5
IDRAC_LOGIN_RETRY_COUNT = 3
IDRAC_LOGIN_RETRY_DELAY = 10

IDRAC_JOB_ALREADY_RUNNING_MESSAGE_ID = "IDRAC.2.8.RAC0679"
IDRAC_SERVER_ALREADY_POWERED_MESSAGE_ID = "IDRAC.2.8.PSU501"
IDRAC_ACCESS_DENIED_MESSAGE_ID = "Base.1.8.AccessDenied"


class VirtualMediaStateException(LisaException):
    pass


@dataclass
class VirtualMediaState:
    """Represents the state of a virtual media device."""

    inserted: bool
    """Whether media is currently inserted in the device."""

    image_name: Optional[str] = None
    """Name of the inserted image file, if any."""

    write_protected: Optional[bool] = None
    """Whether the media is write-protected."""

    image_url: Optional[str] = None
    """Source URI reported by the controller."""


class IdracStartStop(features.StartStop):
    def _login(self) -> None:
        platform: BareMetalPlatform = self._platform  # type: ignore
        self.cluster: Idrac = platform.cluster  # type: ignore
        self.cluster.login()

    def _logout(self) -> None:
        platform: BareMetalPlatform = self._platform  # type: ignore
        self.cluster = platform.cluster  # type: ignore
        self.cluster.logout()

    def _stop(
        self, wait: bool = True, state: features.StopState = features.StopState.Shutdown
    ) -> None:
        if state == features.StopState.Hibernate:
            raise NotImplementedError(
                "baremetal orchestrator does not support hibernate stop"
            )
        self._login()
        self.cluster.reset("GracefulShutdown")
        self._logout()

    def _start(self, wait: bool = True) -> None:
        self._login()
        self.cluster.reset("On")
        self._logout()

    def _restart(self, wait: bool = True) -> None:
        self._login()
        self.cluster.reset("ForceRestart", force_run=True)
        self._logout()


class IdracSerialConsole(features.SerialConsole):
    def _login(self) -> None:
        platform: BareMetalPlatform = self._platform  # type: ignore
        self.cluster: Idrac = platform.cluster  # type: ignore
        self.cluster.login()

    def _logout(self) -> None:
        platform: BareMetalPlatform = self._platform  # type: ignore
        self.cluster = platform.cluster  # type: ignore
        self.cluster.logout()

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        self._login()
        if saved_path:
            screenshot_file_name: str = "serial_console"
            decoded_data = base64.b64decode(self.cluster.get_server_screen_shot())
            screenshot_raw_name = saved_path / f"{screenshot_file_name}.png"
            with open(screenshot_raw_name, "wb") as img_file:
                img_file.write(decoded_data)
        console_log = self.cluster.get_serial_console_log().encode("utf-8")
        self._logout()
        return console_log


class Idrac(Cluster):
    state_dict = {
        "GracefulShutdown": "Off",
        "ForceRestart": "On",
        "On": "On",
        "ForceOff": "Off",
    }

    def __init__(self, runbook: ClusterSchema, **kwargs: Any) -> None:
        super().__init__(runbook, **kwargs)
        self.idrac_runbook: IdracSchema = self.runbook
        assert_that(len(self.idrac_runbook.client)).described_as(
            "only one client is supported for idrac, don't specify more than one client"
        ).is_equal_to(1)

        self._enable_serial_console()

    @classmethod
    def type_name(cls) -> str:
        return "idrac"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return IdracSchema

    def get_start_stop(self) -> Type[features.StartStop]:
        return IdracStartStop

    def get_serial_console(self) -> Type[features.SerialConsole]:
        return IdracSerialConsole

    def deploy(self, environment: Environment) -> Any:
        try:
            self.login()
            client_runbook: IdracClientSchema = self.client.get_extended_runbook(
                IdracClientSchema, "idrac"
            )
            assert (
                client_runbook.iso_http_url
            ), "iso_http_url is required for idrac client"
            self._ensure_controller_is_idle()
            self.reset("ForceOff")
            self._insert_virtual_media(client_runbook.iso_http_url)
            # Media recovery may reset the controller, so arm boot only afterwards.
            self._change_boot_order_once("VCD-DVD")
            self._wait_for_media_inserted(client_runbook.iso_http_url)
            self.reset("On", force_run=True)
        finally:
            # Ensure logout happens even if deployment fails
            self.logout()

    def recover_deployment(self, environment: Environment) -> None:
        self._log.info(
            "Deployment was not verified. Resetting iDRAC and retrying the complete "
            "ISO deployment once; a disk-only reboot is not recovery."
        )
        try:
            self.login()
            self._reset_idrac()
        finally:
            self.logout()
        self.deploy(environment)

    def cleanup(self) -> None:
        try:
            self.login()
            self._clear_serial_console_log()
        except Exception as e:
            # If login fails during cleanup (e.g., session limit), log debug
            # but don't fail cleanup - the system may already be in a clean state
            self._log.debug(
                f"Failed to login for cleanup (this may be expected if "
                f"sessions are exhausted): {e}"
            )
        finally:
            self.logout()

    def get_client_capability(self, client: ClientSchema) -> schema.Capability:
        if client.capability:
            return client.capability

        # Retry capability detection in case iDRAC is initializing
        for attempt in range(3):
            try:
                self.login()
                try:
                    response = self.redfish_instance.get(
                        "/redfish/v1/Systems/System.Embedded.1/",
                    )

                    # Log response structure for debugging
                    self._log.debug(
                        f"iDRAC capability response keys (attempt {attempt + 1}): "
                        f"{list(response.dict.keys())}"
                    )

                    capability = schema.Capability()

                    # Handle missing ProcessorSummary gracefully
                    processor_summary = response.dict.get("ProcessorSummary", {})
                    if "LogicalProcessorCount" in processor_summary:
                        capability.core_count = int(
                            processor_summary["LogicalProcessorCount"]
                        )
                    elif "Count" in processor_summary:
                        capability.core_count = int(processor_summary["Count"])
                    else:
                        # Missing processor info - might be transient
                        raise LisaException(
                            f"Unable to get processor count from iDRAC response. "
                            f"ProcessorSummary keys: {list(processor_summary.keys())}, "
                            f"Response keys: {list(response.dict.keys())}"
                        )

                    # Handle missing MemorySummary gracefully
                    memory_summary = response.dict.get("MemorySummary", {})
                    if "TotalSystemMemoryGiB" in memory_summary:
                        capability.memory_mb = (
                            int(memory_summary["TotalSystemMemoryGiB"]) * 1024
                        )
                    else:
                        # Missing memory info - might be transient
                        raise LisaException(
                            f"Unable to get memory size from iDRAC response. "
                            f"MemorySummary keys: {list(memory_summary.keys())}, "
                            f"Response keys: {list(response.dict.keys())}"
                        )

                    return capability
                finally:
                    # Always logout, regardless of success or failure
                    self.logout()

            except Exception as e:
                if attempt < 2:  # Not last attempt
                    self._log.warning(
                        f"Failed to get capability (attempt {attempt + 1}/3): {e}. "
                    )

                    # On second failure, try resetting iDRAC
                    if attempt == 1:
                        self._log.warning(
                            "iDRAC may be in unstable state. Attempting iDRAC reset..."
                        )
                        try:
                            self._reset_idrac()
                            # _reset_idrac() leaves session logged in, clean it up
                            self.logout()
                            time.sleep(30)  # Give iDRAC time to restart
                        except Exception as reset_error:
                            self._log.warning(
                                f"iDRAC reset failed: {reset_error}. "
                                f"Will retry capability detection anyway."
                            )
                    else:
                        # First failure - simple retry with short delay
                        self._log.warning("Retrying in 5 seconds...")
                        time.sleep(5)
                else:
                    # Last attempt failed - re-raise
                    raise

        # Should never reach here due to raise above, but satisfy mypy
        raise LisaException("Failed to get iDRAC capability after all retries")

    def get_serial_console_log(self) -> str:
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/SerialInterfaces"
            "/Serial.1/Actions/Oem/DellSerialInterface.SerialDataExport",
            body={},
        )
        check_till_timeout(
            lambda: int(response.status) == 200,
            timeout_message="wait for response status 200",
        )
        return str(response.text)

    def get_server_screen_shot(self, file_type: str = "ServerScreenShot") -> str:
        response = self.redfish_instance.post(
            "/redfish/v1/Dell/Managers/iDRAC.Embedded.1/DellLCService/Actions/"
            "DellLCService.ExportServerScreenShot",
            body={"FileType": file_type},
        )
        self._wait_for_completion(response)
        return str(response.dict["ServerScreenShotFile"])

    def reset(self, operation: str, force_run: bool = False) -> None:
        expected_state = self.state_dict.get(operation)
        if expected_state:
            if not force_run and self.get_power_state() == expected_state:
                self._log.debug(f"System is already in {expected_state} state.")
                return

        body = {"ResetType": operation}
        url = "/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset"

        def _post_reset() -> None:
            response = self.redfish_instance.post(url, body=body)
            self._wait_for_completion(response)

        # Try reset operation with iDRAC recovery on HTTP 500 errors
        try:
            self._run_with_idrac_job_retry(
                f"ComputerSystem.Reset '{operation}'",
                _post_reset,
            )
        except LisaException as e:
            error_msg = str(e)
            if expected_state and self._is_already_in_expected_state_error(
                error_msg,
                expected_state,
            ):
                self._log.debug(
                    f"ComputerSystem.Reset '{operation}' reported that the server "
                    f"is already in '{expected_state}' state. Continuing."
                )
            elif self._reset_if_idrac_error(error_msg):
                # iDRAC was reset, retry the operation once
                self._run_with_idrac_job_retry(
                    f"ComputerSystem.Reset '{operation}' after iDRAC reset",
                    _post_reset,
                )
            else:
                # Not a retriable iDRAC error - re-raise original exception
                raise

        if expected_state:
            check_till_timeout(
                lambda: self.get_power_state() == expected_state,
                timeout_message=(f"wait for client into '{expected_state}' state"),
            )
        self._log.debug(f"{operation} initiated successfully.")

    @retry(tries=3, delay=5)  # type: ignore
    def get_power_state(self) -> str:
        response = self.redfish_instance.get(
            "/redfish/v1/Systems/System.Embedded.1/",
        )
        response_dict = response.dict
        power_state = response_dict.get("PowerState")
        if power_state is not None:
            return str(power_state)

        status = getattr(response, "status", "unknown")
        response_keys = list(response_dict.keys())
        error_msg = (
            "Failed to get iDRAC power state because the System endpoint response "
            f"did not include a non-null PowerState. "
            f"status={status}, keys={response_keys}. "
            "Verify the iDRAC System endpoint and Lifecycle Controller health."
        )
        if self._reset_if_idrac_error(error_msg):
            raise LisaException(f"{error_msg} iDRAC reset completed; retrying.")
        raise LisaException(error_msg)

    @retry(tries=IDRAC_LOGIN_RETRY_COUNT, delay=IDRAC_LOGIN_RETRY_DELAY)  # type: ignore
    def login(self) -> None:
        self.redfish_instance = redfish.redfish_client(
            base_url="https://" + self.idrac_runbook.address,
            username=self.idrac_runbook.username,
            password=self.idrac_runbook.password,
        )
        self.redfish_instance.login(auth="session")
        self._log.debug(f"Login to {self.redfish_instance.get_base_url()} successful.")

    def logout(self) -> None:
        """Safely logout, catching and logging any errors."""
        try:
            if hasattr(self, "redfish_instance") and self.redfish_instance:
                self._log.debug("Logging out...")
                self.redfish_instance.logout()
        except Exception as e:
            self._log.debug(f"Error during logout (session may already be closed): {e}")

    def _wait_for_completion(self, response: Any, timeout: int = 600) -> None:
        timer = create_timer()
        task = response
        while True:
            self._check_response_status(task)
            data = task.dict if task.status != 204 and task.text else {}
            if not isinstance(data, dict):
                raise LisaException(f"Invalid iDRAC asynchronous response: {data}")
            states = [data[key] for key in ("TaskState", "JobState") if key in data]
            if (
                "error" in data
                or data.get("TaskStatus") == "Critical"
                or any(
                    state
                    in (
                        "Exception",
                        "Failed",
                        "Cancelled",
                        "Canceled",
                        "Killed",
                        "Interrupted",
                        "CompletedWithErrors",
                    )
                    for state in states
                )
            ):
                raise LisaException(f"iDRAC asynchronous operation failed: {data}")
            if (
                not task.is_processing
                and task.status != 202
                and all(state in ("Completed", "RebootCompleted") for state in states)
            ):
                if data.get("TaskStatus") == "Warning":
                    self._log.info(
                        f"iDRAC asynchronous operation completed with warnings: {data}"
                    )
                return
            remaining = timeout - timer.elapsed(False)
            if remaining <= 0:
                raise LisaException(
                    f"iDRAC asynchronous operation did not complete within "
                    f"{timeout} seconds; last response: {data}"
                )
            retry_time = task.retry_after
            if retry_time is not None and (
                not isinstance(retry_time, (int, float)) or retry_time < 0
            ):
                raise LisaException(f"Invalid iDRAC retry interval: {retry_time!r}")
            time.sleep(min(retry_time or 5, remaining))
            task = response.monitor(self.redfish_instance)

    @staticmethod
    def _check_response_status(response: Any) -> None:
        if response.status not in (200, 201, 202, 204):
            raise LisaException(
                f"iDRAC API request failed with status {response.status}: "
                f"{response.text}"
            )

    def _run_with_idrac_job_retry(
        self,
        operation_description: str,
        operation: Callable[[], None],
    ) -> None:
        access_denied_recovered = False

        def _try_operation() -> bool:
            nonlocal access_denied_recovered
            try:
                operation()
                return True
            except LisaException as e:
                if self._is_access_denied_error(str(e)):
                    if access_denied_recovered:
                        raise
                    access_denied_recovered = True
                    self._refresh_session_after_access_denied(operation_description)
                    return False
                if not self._is_idrac_job_already_running_error(str(e)):
                    raise
                self._log.debug(
                    f"{operation_description} is waiting on an existing iDRAC "
                    f"job to complete: {e}"
                )
                return False

        check_till_timeout(
            _try_operation,
            timeout_message=(
                f"wait for existing iDRAC job before {operation_description}"
            ),
            timeout=IDRAC_JOB_QUEUE_TIMEOUT,
            interval=IDRAC_JOB_QUEUE_POLL_INTERVAL,
        )

    @staticmethod
    def _is_idrac_job_already_running_error(error_str: str) -> bool:
        normalized_error = error_str.lower()
        return (
            IDRAC_JOB_ALREADY_RUNNING_MESSAGE_ID.lower() in normalized_error
            or "a job operation is already running" in normalized_error
        )

    @staticmethod
    def _is_already_in_expected_state_error(
        error_str: str,
        expected_state: str,
    ) -> bool:
        normalized_error = error_str.lower()
        expected_state = expected_state.lower()
        if expected_state == "on" and (
            IDRAC_SERVER_ALREADY_POWERED_MESSAGE_ID.lower() in normalized_error
        ):
            return True
        return f"server is already powered {expected_state}" in normalized_error

    @staticmethod
    def _is_access_denied_error(error_str: str) -> bool:
        normalized_error = error_str.lower()
        return (
            IDRAC_ACCESS_DENIED_MESSAGE_ID.lower() in normalized_error
            or "accessdenied" in normalized_error
            or "access denied" in normalized_error
            or "credentials included with this request are missing or invalid"
            in normalized_error
            or "status 401" in normalized_error
            or "status 403" in normalized_error
        )

    def _refresh_session_after_access_denied(self, operation_description: str) -> None:
        self._log.debug(
            f"{operation_description} received iDRAC access denied. "
            "Refreshing the Redfish session before retrying."
        )
        self.logout()
        self.login()

    def _eject_vm(self, device_name: str) -> None:
        """Eject virtual media from specified device (CD or RemovableDisk)."""
        response = self.redfish_instance.post(
            f"/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/{device_name}/"
            "Actions/VirtualMedia.EjectMedia",
            body={},
        )
        self._wait_for_completion(response)

    def _get_vm_state(self, device_name: str = "CD") -> VirtualMediaState:
        """Get virtual media state for specified device."""
        response = self.redfish_instance.get(
            f"/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/{device_name}"
        )
        if response.status != 200:
            raise LisaException(
                f"iDRAC virtual media query failed with status {response.status}: "
                f"{response.text}"
            )
        try:
            data = response.dict
        except JsonDecodingError as error:
            raise VirtualMediaStateException(
                f"iDRAC returned malformed state for virtual media {device_name}"
            ) from error
        if not isinstance(data, dict) or not isinstance(data.get("Inserted"), bool):
            raise VirtualMediaStateException(
                f"iDRAC returned an invalid state for virtual media "
                f"{device_name}: {data}"
            )
        image_url = data.get("Image")
        if image_url is not None and not isinstance(image_url, str):
            raise VirtualMediaStateException(
                f"iDRAC returned an invalid image URI for {device_name}: {image_url!r}"
            )
        return VirtualMediaState(
            inserted=data["Inserted"],
            image_name=data.get("ImageName"),
            write_protected=data.get("WriteProtected"),
            image_url=image_url,
        )

    def _ensure_vm_cleared(self) -> None:
        """Ensure both CD and RemovableDisk are ejected and wait for completion."""
        for device in ("CD", "RemovableDisk"):
            state = self._get_vm_state(device)
            if state.inserted:
                self._log.debug(f"Ejecting {device}...")
                self._eject_vm(device)

        # Poll up to 30s for both devices to show Inserted=false
        def _check_vm_cleared() -> bool:
            cd_state = self._get_vm_state("CD").inserted
            rd_state = self._get_vm_state("RemovableDisk").inserted
            if not cd_state and not rd_state:
                self._log.debug("All virtual media ejected successfully")
                return True
            return False

        try:
            check_till_timeout(
                _check_vm_cleared,
                timeout_message="Virtual media still inserted after ejection",
                timeout=VIRTUAL_MEDIA_EJECT_TIMEOUT,
                interval=1,
            )
        except LisaException as error:
            raise VirtualMediaStateException(
                f"Virtual media could not be verified ejected: {error}"
            ) from error

    def _reset_if_idrac_error(self, error_str: str) -> bool:
        """
        Check if error indicates iDRAC internal issues and reset if needed.

        Args:
            error_str: The error message string to check

        Returns:
            True if this was an iDRAC error that triggered a reset, False otherwise

        This method checks for specific iDRAC internal error message IDs.
        These message IDs are part of the Redfish standard and DMTF Base Registry:
        - IDRAC.2.8.SYS446: Dell iDRAC-specific message (stable across versions)
        - IDRAC.2.8.RAC0508: Lifecycle Controller/provider not ready
        - Base.1.12.InternalError: DMTF standard message (version-independent)

        These indicate transient iDRAC service errors that can resolve after reset.
        Reference: DMTF DSP0268 (Message Registry Guide)
        """
        normalized_error = error_str.lower()
        is_idrac_internal_error = (
            "idrac.2.8.sys446" in normalized_error
            or "idrac.2.8.rac0508" in normalized_error
            or "base.1.12.internalerror" in normalized_error
            or "provider is not ready" in normalized_error
            or "status=500" in normalized_error
            or "status 500" in normalized_error
        )

        if is_idrac_internal_error:
            # Per error message: "If the problem persists, consider resetting
            # the service."
            self._log.debug(
                "iDRAC internal server error detected. "
                "Resetting iDRAC service per error message guidance..."
            )
            self._reset_idrac()
            return True

        return False

    def _reset_idrac(self) -> None:
        """
        Reset iDRAC to recover from internal errors and clear stale state.

        Handles session invalidation properly by logging out before reset
        and re-logging in after iDRAC restarts.
        """
        self._ensure_controller_is_idle()
        self._log.info("Resetting iDRAC to recover from internal error...")

        # Send reset request without waiting for completion
        # (to avoid recursion through _wait_for_completion)
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Actions/Manager.Reset",
            body={"ResetType": "GracefulRestart"},
        )

        # Just check the immediate response status
        self._check_response_status(response)

        # Logout old session (will be invalidated by iDRAC reset anyway)
        self._log.debug("Logging out before iDRAC restart...")
        self.logout()

        # Poll for iDRAC manager reachability first.
        self._log.debug("Waiting for iDRAC manager API to become ready...")

        def _try_login() -> bool:
            try:
                self.login()
                # Verify we can actually query the manager
                mgr_state = self.redfish_instance.get(
                    "/redfish/v1/Managers/iDRAC.Embedded.1"
                ).dict
                if mgr_state.get("Status", {}).get("State") == "Enabled":
                    return True
                # Not enabled yet
                self.logout()
                return False
            except Exception as e:
                # iDRAC may still be restarting, ignore connection errors
                self._log.debug(f"iDRAC not ready yet: {e}")
                return False

        check_till_timeout(
            _try_login,
            timeout_message="iDRAC did not recover after reset",
            timeout=IDRAC_RESET_TIMEOUT,
            interval=5,
        )

        self._wait_for_remote_services_ready()
        self._log.info("iDRAC reset completed successfully")

    def _ensure_controller_is_idle(self) -> None:
        manager = "/redfish/v1/Managers/iDRAC.Embedded.1"
        response = self.redfish_instance.get(f"{manager}/Jobs")
        self._check_response_status(response)
        data = response.dict
        if not isinstance(data, dict):
            raise LisaException("Cannot verify the iDRAC job queue response")
        members = data.get("Members")
        count = data.get("Members@odata.count")
        if (
            response.status != 200
            or not isinstance(members, list)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count != len(members)
            or data.get("Members@odata.nextLink")
        ):
            raise LisaException(
                "Cannot verify the complete iDRAC job queue; "
                "refusing deployment or controller reset"
            )
        for member in members:
            if not isinstance(member, dict):
                raise LisaException(f"Cannot verify iDRAC job entry: {member}")
            path = member.get("@odata.id")
            if not isinstance(path, str) or not path.startswith(
                (f"{manager}/Jobs/", f"{manager}/Oem/Dell/Jobs/")
            ):
                raise LisaException(f"Cannot verify iDRAC job resource: {member}")
            job_response = self.redfish_instance.get(path)
            self._check_response_status(job_response)
            job = job_response.dict
            if (
                job_response.status != 200
                or not isinstance(job, dict)
                or job.get("JobState")
                not in (
                    "Completed",
                    "CompletedWithErrors",
                    "RebootCompleted",
                    "Failed",
                    "Cancelled",
                    "Canceled",
                )
            ):
                raise LisaException(
                    "Refusing deployment or controller reset while a job "
                    "is active or unverified: "
                    f"{job}. No jobs were cancelled or removed."
                )

    def _wait_for_remote_services_ready(self) -> None:
        """
        Wait for Lifecycle Controller remote services to report ready.

        Manager availability is not sufficient for operations like
        ImportSystemConfiguration. Those depend on the Lifecycle Controller
        provider, which can still be initializing after the manager API is
        reachable again.
        """

        self._log.debug(
            "Waiting for iDRAC Lifecycle Controller provider to become ready..."
        )

        def _remote_services_ready() -> bool:
            try:
                response = self.redfish_instance.post(
                    "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/"
                    "DellLCService/Actions/"
                    "DellLCService.GetRemoteServicesAPIStatus",
                    body={},
                )
                if response.status != 200:
                    self._log.debug(
                        "iDRAC remote services status check returned "
                        f"HTTP {response.status}"
                    )
                    return False

                remote_services = response.dict
                lc_status = str(remote_services.get("LCStatus", "Unknown"))
                rt_status = remote_services.get("RTStatus")
                rt_status_str = str(rt_status) if rt_status is not None else "Unknown"

                if lc_status == "Ready" and (
                    rt_status is None or rt_status_str == "Ready"
                ):
                    self._log.debug(
                        "iDRAC remote services ready: "
                        f"LCStatus={lc_status}, RTStatus={rt_status_str}"
                    )
                    return True

                self._log.debug(
                    "iDRAC remote services not ready yet: "
                    f"LCStatus={lc_status}, RTStatus={rt_status_str}"
                )
                return False
            except JsonDecodingError as e:
                self._log.debug(
                    "iDRAC remote services status returned invalid JSON: " f"{e}"
                )
                return False
            except Exception as e:
                self._log.debug(f"iDRAC remote services not ready yet: {e}")
                return False

        check_till_timeout(
            _remote_services_ready,
            timeout_message=(
                "iDRAC remote services did not become ready after reset. "
                "Check Lifecycle Controller status and the LC job queue in the "
                "iDRAC UI or logs for stuck or failed jobs, and increase "
                "IDRAC_REMOTE_SERVICES_TIMEOUT if this platform is slow to "
                "initialize remote services."
            ),
            timeout=IDRAC_REMOTE_SERVICES_TIMEOUT,
            interval=5,
        )

    def _insert_virtual_media(self, iso_http_url: str) -> None:
        """Insert virtual media with robust error handling and retry logic."""
        self._log.info(f"Inserting virtual media from URL: {iso_http_url}")
        for attempt in range(2):
            try:
                self._ensure_vm_cleared()
                time.sleep(5)
                response = self.redfish_instance.post(
                    "/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD/"
                    "Actions/VirtualMedia.InsertMedia",
                    body={"Image": iso_http_url, "TransferProtocolType": "NFS"},
                )
                self._wait_for_completion(response)
                self._wait_for_media_inserted(iso_http_url)
                return
            except LisaException as error:
                if attempt:
                    raise
                message = str(error)
                self._log.info(
                    f"Virtual media setup failed; one retry remains: {error}"
                )
                if self._is_access_denied_error(message):
                    self._refresh_session_after_access_denied("virtual media setup")
                elif (
                    isinstance(error, VirtualMediaStateException)
                    or "VRM0021" in message
                    or "RAC0904" in message
                    or "not accessible or reachable" in message
                ):
                    self._reset_idrac()
                elif not self._reset_if_idrac_error(message):
                    raise

    def _wait_for_media_inserted(self, iso_http_url: str) -> None:
        def _matches_requested_image() -> bool:
            state = self._get_vm_state("CD")
            return state.inserted and state.image_url == iso_http_url

        try:
            check_till_timeout(
                _matches_requested_image,
                timeout_message="wait for the requested ISO to be inserted",
                timeout=VIRTUAL_MEDIA_INSERTION_POLL_TIMEOUT,
                interval=1,
            )
        except LisaException as error:
            raise VirtualMediaStateException(
                f"The requested ISO was not verified in virtual media: {error}"
            ) from error
        self._log.info("Verified the requested ISO is inserted")

    def _change_boot_order_once(self, boot_from: str) -> None:
        self._log.debug(f"Updating boot source to {boot_from}")
        sys_config = ETree.Element("SystemConfiguration")
        component = ETree.SubElement(
            sys_config, "Component", {"FQDD": "iDRAC.Embedded.1"}
        )
        boot_once_attribute = ETree.SubElement(
            component, "Attribute", {"Name": "VirtualMedia.1#BootOnce"}
        )
        boot_once_attribute.text = "Enabled"
        first_boot_attribute = ETree.SubElement(
            component, "Attribute", {"Name": "ServerBoot.1#FirstBootDevice"}
        )
        first_boot_attribute.text = boot_from
        import_buffer = ETree.tostring(
            sys_config, encoding="utf8", method="html"
        ).decode()

        body = {"ShareParameters": {"Target": "ALL"}, "ImportBuffer": import_buffer}
        url = (
            "/redfish/v1/Managers/iDRAC.Embedded.1/Actions/Oem/"
            "EID_674_Manager.ImportSystemConfiguration"
        )

        try:
            self._run_with_idrac_job_retry(
                "boot order override",
                lambda: self._post_boot_order_override(url, body),
            )
        except LisaException as e:
            if self._reset_if_idrac_error(str(e)):
                self._log.debug(
                    "Retrying boot order override after iDRAC reset recovery..."
                )
                self._run_with_idrac_job_retry(
                    "boot order override after iDRAC reset",
                    lambda: self._post_boot_order_override(url, body),
                )
            else:
                raise

        self._log.debug(f"Updating boot source to {boot_from} completed")

    def _post_boot_order_override(self, url: str, body: Any) -> None:
        response = self.redfish_instance.post(url, body=body)
        self._log.debug("Waiting for boot order override task to complete...")
        self._wait_for_completion(response)

    def _enable_serial_console(self) -> None:
        # iDRAC may return 503 Service Unavailable transiently (e.g. just after
        # a reset or during initialisation). Retry for up to IDRAC_RESET_TIMEOUT
        # seconds before giving up.
        def _try_enable() -> bool:
            try:
                self.login()
                response = self.redfish_instance.get(
                    "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes"
                )
                attributes = response.dict.get("Attributes", {})
                serial_capture_enabled = attributes.get(
                    "SerialCapture.1.Enable", "Disabled"
                )

                # Treat missing attribute as "Disabled" and attempt to enable
                if serial_capture_enabled != "Enabled":
                    self._log.debug(
                        f"Serial console is '{serial_capture_enabled}'. Enabling..."
                    )
                    self.redfish_instance.patch(
                        "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes",
                        body={"Attributes": {"SerialCapture.1.Enable": "Enabled"}},
                    )

                # Verify it's enabled
                response = self.redfish_instance.get(
                    "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes"
                )
                attributes = response.dict.get("Attributes", {})
                final_state = attributes.get("SerialCapture.1.Enable", "Unknown")
                if final_state == "Enabled":
                    self._log.debug("Serial console enabled successfully.")
                    return True
                raise LisaException(
                    f"Failed to enable serial console. Current state: {final_state}"
                )
            except JsonDecodingError as e:
                # iDRAC returned a non-JSON response (e.g. 503 HTML page);
                # log and signal caller to retry.
                self._log.info(
                    f"iDRAC returned invalid JSON (likely 503 transient error): "
                    f"{e}. Retrying..."
                )
                return False
            except RetriesExhaustedError as e:
                self._log.info(
                    "iDRAC serial console setup could not reach Redfish: "
                    f"{e}. Retrying..."
                )
                return False
            finally:
                self.logout()

        check_till_timeout(
            _try_enable,
            timeout_message=(
                "iDRAC Attributes endpoint unavailable after retries "
                "(repeated Redfish connection failures or invalid JSON responses)"
            ),
            timeout=IDRAC_RESET_TIMEOUT,
            interval=10,
        )

    def _clear_serial_console_log(self) -> None:
        response = self.redfish_instance.get(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes"
        )
        attributes = response.dict.get("Attributes", {})
        if attributes.get("SerialCapture.1.Enable") == "Disabled":
            self._log.debug("Serial console is already disabled. No need to clear log.")
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/SerialInterfaces"
            "/Serial.1/Actions/Oem/DellSerialInterface.SerialDataClear",
            body={},
        )
        self._wait_for_completion(response)
