# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import time
import xml.etree.ElementTree as ETree
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Type

import redfish
from assertpy import assert_that
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
VIRTUAL_MEDIA_INSERTION_POLL_TIMEOUT = 30


@dataclass
class VirtualMediaState:
    """Represents the state of a virtual media device."""

    inserted: bool
    """Whether media is currently inserted in the device."""

    image_name: Optional[str] = None
    """Name of the inserted image file, if any."""

    write_protected: Optional[bool] = None
    """Whether the media is write-protected."""


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
            self._change_boot_order_once("VCD-DVD")
            self.reset("ForceOff")
            self._insert_virtual_media(client_runbook.iso_http_url)
            self.reset("On", force_run=True)
        finally:
            # Ensure logout happens even if deployment fails
            self.logout()

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
        if operation in self.state_dict.keys():
            expected_state = self.state_dict[operation]
            if not force_run and self.get_power_state() == expected_state:
                self._log.debug(f"System is already in {expected_state} state.")
                return

        body = {"ResetType": operation}

        # Try reset operation with iDRAC recovery on HTTP 500 errors
        try:
            response = self.redfish_instance.post(
                "/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset",
                body=body,
            )
            self._wait_for_completion(response)
        except LisaException as e:
            if self._reset_if_idrac_error(str(e)):
                # iDRAC was reset, retry the operation once
                url = (
                    "/redfish/v1/Systems/System.Embedded.1/Actions/"
                    "ComputerSystem.Reset"
                )
                response = self.redfish_instance.post(url, body=body)
                self._wait_for_completion(response)
            else:
                # Not a retriable iDRAC error - re-raise original exception
                raise

        if operation in self.state_dict.keys():
            check_till_timeout(
                lambda: self.get_power_state() == expected_state,
                timeout_message=(f"wait for client into '{expected_state}' state"),
            )
        self._log.debug(f"{operation} initiated successfully.")

    def get_power_state(self) -> str:
        response = self.redfish_instance.get(
            "/redfish/v1/Systems/System.Embedded.1/",
        )
        return str(response.dict["PowerState"])

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
        if response.is_processing:
            task = response.monitor(self.redfish_instance)
            timer = create_timer()
            while task.is_processing and timer.elapsed(False) < timeout:
                retry_time = task.retry_after
                time.sleep(retry_time if retry_time else 5)
                task = response.monitor(self.redfish_instance)

        if response.status not in [200, 202, 204]:
            # Include response details for better debugging
            error_msg = f"iDRAC API request failed with status {response.status}"
            if hasattr(response, "text"):
                error_msg += f", response: {response.text}"
            if hasattr(response, "dict"):
                error_msg += f", details: {response.dict}"
            raise LisaException(error_msg)

    def _eject_vm(self, device_name: str) -> None:
        """Eject virtual media from specified device (CD or RemovableDisk)."""
        response = self.redfish_instance.post(
            f"/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/{device_name}/"
            "Actions/VirtualMedia.EjectMedia",
            body={},
        )
        # Ignore errors - device may not have media inserted
        if response.status in [200, 202, 204]:
            self._wait_for_completion(response)

    def _get_vm_state(self, device_name: str = "CD") -> VirtualMediaState:
        """Get virtual media state for specified device."""
        response = self.redfish_instance.get(
            f"/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/{device_name}"
        )
        data = response.dict
        return VirtualMediaState(
            inserted=data.get("Inserted", False),
            image_name=data.get("ImageName"),
            write_protected=data.get("WriteProtected"),
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
        except Exception:
            # Don't fail if media appears stuck; log and continue
            self._log.debug(
                "VirtualMedia still appears inserted after ejects; continuing."
            )

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
        - Base.1.12.InternalError: DMTF standard message (version-independent)

        Both indicate transient iDRAC service errors that resolve after reset.
        Reference: DMTF DSP0268 (Message Registry Guide)
        """
        is_idrac_internal_error = (
            "IDRAC.2.8.SYS446" in error_str or "Base.1.12.InternalError" in error_str
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
        self._log.info("Resetting iDRAC to recover from internal error...")

        # Send reset request without waiting for completion
        # (to avoid recursion through _wait_for_completion)
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Actions/Manager.Reset",
            body={"ResetType": "GracefulRestart"},
        )

        # Just check the immediate response status
        if response.status not in [200, 202, 204]:
            self._log.debug(
                f"iDRAC reset request returned status {response.status}, "
                f"continuing anyway"
            )

        # Logout old session (will be invalidated by iDRAC reset anyway)
        self._log.debug("Logging out before iDRAC restart...")
        self.logout()

        # Poll for iDRAC readiness (typically takes 3-4 minutes)
        self._log.debug("Waiting for iDRAC to restart and become ready...")

        def _try_login() -> bool:
            try:
                self.login()
                # Verify we can actually query the manager
                mgr_state = self.redfish_instance.get(
                    "/redfish/v1/Managers/iDRAC.Embedded.1"
                ).dict
                if mgr_state.get("Status", {}).get("State") == "Enabled":
                    self._log.info("iDRAC reset completed successfully")
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

    def _insert_virtual_media(self, iso_http_url: str) -> None:
        """Insert virtual media with robust error handling and retry logic."""
        self._log.info(f"Inserting virtual media from URL: {iso_http_url}")

        # Step 1: Ensure all virtual media is ejected
        self._ensure_vm_cleared()

        # Step 2: Sleep to let iDRAC drop any stale NFS/HTTP handles
        time.sleep(5)

        # Step 3: Try insert with retries and iDRAC reset if needed
        self._insert_virtual_media_with_retry(iso_http_url)

    @retry(tries=3, delay=0)  # type: ignore
    def _insert_virtual_media_with_retry(self, iso_http_url: str) -> None:
        """Perform virtual media insertion with automatic retry."""
        try:
            # Explicitly specify NFS protocol (helps across firmware revisions)
            body = {"Image": iso_http_url, "TransferProtocolType": "NFS"}
            response = self.redfish_instance.post(
                "/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD/"
                "Actions/VirtualMedia.InsertMedia",
                body=body,
            )
            self._wait_for_completion(response)

            # Verify insertion by polling CD state
            def _check_media_inserted() -> bool:
                if self._get_vm_state("CD").inserted:
                    self._log.info("Virtual media insertion completed successfully")
                    return True
                return False

            check_till_timeout(
                _check_media_inserted,
                timeout_message=(
                    "Insert reported success but CD not showing as Inserted"
                ),
                timeout=VIRTUAL_MEDIA_INSERTION_POLL_TIMEOUT,
                interval=1,
            )

        except LisaException as e:
            error_msg = str(e)

            # Check for HTTP 500 internal server errors and reset if needed
            if self._reset_if_idrac_error(error_msg):
                # Re-raise to trigger retry
                raise

            # Check for VRM0021 virtual media attach mode errors that need iDRAC reset
            # VRM0021: "Virtual Media is detached or Virtual Media devices are already
            # in use" - indicates attach mode is wrong or stale session exists
            if "VRM0021" in error_msg:
                self._log.debug(
                    "VRM0021 virtual media attach error detected. "
                    "Ejecting media, resetting iDRAC to clear stale sessions..."
                )
                # Clear virtual media and reset iDRAC to fix attach mode/clear sessions
                self._ensure_vm_cleared()
                self._reset_idrac()
                # Re-raise to trigger retry
                raise

            # Check for RAC0904 or reachability errors that need iDRAC reset
            is_reachability_error = (
                "RAC0904" in error_msg or "not accessible or reachable" in error_msg
            )

            if is_reachability_error:
                # RAC0904 errors occur when iDRAC has stale NFS/HTTP handles from
                # previous operations. This is a known iDRAC firmware quirk where the
                # controller caches connection state even after media is ejected.
                # Clearing media ensures no residual handles exist, and resetting
                # iDRAC clears its internal cache, allowing the next insert attempt
                # to establish a fresh connection to the NFS/HTTP server.
                self._log.debug(
                    "RAC0904/reachability error detected. "
                    "Ejecting media, resetting iDRAC, and retrying..."
                )
                # Clear virtual media and reset iDRAC to clear stale state
                self._ensure_vm_cleared()
                self._reset_idrac()
                # Re-raise to trigger retry
                raise

            # Non-reachability error - include original error details
            raise LisaException(
                f"Failed to insert virtual media from '{iso_http_url}'. "
                f"Ensure the iDRAC can reach this URL and the file exists. "
                f"iDRAC error: {error_msg}"
            )

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
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Actions/Oem/"
            "EID_674_Manager.ImportSystemConfiguration",
            body=body,
        )

        self._log.debug("Waiting for boot order override task to complete...")
        self._wait_for_completion(response)
        self._log.debug(f"Updating boot source to {boot_from} completed")

    def _enable_serial_console(self) -> None:
        self.login()
        response = self.redfish_instance.get(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes"
        )

        attributes = response.dict.get("Attributes", {})
        serial_capture_enabled = attributes.get("SerialCapture.1.Enable", "Disabled")

        # Treat missing attribute as "Disabled" and attempt to enable
        if serial_capture_enabled != "Enabled":
            self._log.debug(
                f"Serial console is '{serial_capture_enabled}'. Enabling..."
            )
            response = self.redfish_instance.patch(
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
        else:
            raise LisaException(
                f"Failed to enable serial console. Current state: {final_state}"
            )
        self.logout()

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
