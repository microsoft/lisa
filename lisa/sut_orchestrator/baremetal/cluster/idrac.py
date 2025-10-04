# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import time
import xml.etree.ElementTree as ETree
from pathlib import Path
from typing import Any, Dict, Optional, Type

import redfish
from assertpy import assert_that

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
            self._safe_logout()

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
            self._safe_logout()

    def get_client_capability(self, client: ClientSchema) -> schema.Capability:
        if client.capability:
            return client.capability
        self.login()
        response = self.redfish_instance.get(
            "/redfish/v1/Systems/System.Embedded.1/",
        )
        capability = schema.Capability()
        capability.core_count = int(
            response.dict["ProcessorSummary"]["LogicalProcessorCount"]
        )
        capability.memory_mb = (
            int(response.dict["MemorySummary"]["TotalSystemMemoryGiB"]) * 1024
        )
        self.logout()

        return capability

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
        response = self.redfish_instance.post(
            "/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset",
            body=body,
        )
        self._wait_for_completion(response)
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
        self._log.debug("Logging out...")
        self.redfish_instance.logout()

    def _safe_logout(self) -> None:
        """Safely logout, catching and logging any errors."""
        try:
            if hasattr(self, "redfish_instance") and self.redfish_instance:
                self.logout()
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

    def _get_vm_state(self, device_name: str = "CD") -> Dict[str, Any]:
        """Get virtual media state for specified device."""
        response = self.redfish_instance.get(
            f"/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/{device_name}"
        )
        result: Dict[str, Any] = response.dict
        return result

    def _ensure_vm_cleared(self) -> None:
        """Ensure both CD and RemovableDisk are ejected and wait for completion."""
        for device in ("CD", "RemovableDisk"):
            state = self._get_vm_state(device)
            if state.get("Inserted"):
                self._log.debug(f"Ejecting {device}...")
                self._eject_vm(device)

        # Poll up to 30s for both devices to show Inserted=false
        start_time = time.time()
        while time.time() - start_time < VIRTUAL_MEDIA_EJECT_TIMEOUT:
            cd_state = self._get_vm_state("CD").get("Inserted", False)
            rd_state = self._get_vm_state("RemovableDisk").get("Inserted", False)
            if not cd_state and not rd_state:
                self._log.debug("All virtual media ejected successfully")
                return
            time.sleep(1)

        self._log.debug("VirtualMedia still appears inserted after ejects; continuing.")

    def _reset_idrac(self) -> None:
        """Reset iDRAC to clear stale virtual media state."""
        self._log.debug("Resetting iDRAC (GracefulRestart) to clear stale VM state...")
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Actions/Manager.Reset",
            body={"ResetType": "GracefulRestart"},
        )
        self._wait_for_completion(response)

        # Poll manager until Enabled (up to 2 minutes)
        start_time = time.time()
        while time.time() - start_time < IDRAC_RESET_TIMEOUT:
            try:
                mgr_state = self.redfish_instance.get(
                    "/redfish/v1/Managers/iDRAC.Embedded.1"
                ).dict
                if mgr_state.get("Status", {}).get("State") == "Enabled":
                    self._log.info("iDRAC reset completed successfully")
                    return
            except Exception:
                # iDRAC may be restarting, ignore connection errors
                pass
            time.sleep(2)

        raise LisaException("iDRAC did not come back after Manager.Reset")

    def _insert_virtual_media(self, iso_http_url: str) -> None:
        """Insert virtual media with robust error handling and retry logic."""
        self._log.info(f"Inserting virtual media from URL: {iso_http_url}")

        # Step 1: Ensure all virtual media is ejected
        self._ensure_vm_cleared()

        # Step 2: Sleep to let iDRAC drop any stale NFS/HTTP handles
        time.sleep(5)

        # Step 3: Try insert with retries and iDRAC reset if needed
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                # Explicitly specify NFS protocol (helps across firmware revisions)
                body = {"Image": iso_http_url, "TransferProtocolType": "NFS"}
                response = self.redfish_instance.post(
                    "/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD/"
                    "Actions/VirtualMedia.InsertMedia",
                    body=body,
                )
                self._wait_for_completion(response)

                # Step 4: Verify insertion by polling CD state
                start_time = time.time()
                while time.time() - start_time < VIRTUAL_MEDIA_INSERTION_POLL_TIMEOUT:
                    if self._get_vm_state("CD").get("Inserted"):
                        self._log.info("Virtual media insertion completed successfully")
                        return
                    time.sleep(1)

                raise LisaException(
                    "Insert reported success but CD not showing as Inserted"
                )

            except LisaException as e:
                error_msg = str(e)
                # Check for RAC0904 or reachability errors
                is_reachability_error = (
                    "RAC0904" in error_msg or "not accessible or reachable" in error_msg
                )

                if is_reachability_error and attempt < max_attempts:
                    self._log.debug(
                        f"RAC0904/reachability error on attempt {attempt}. "
                        "Ejecting media, resetting iDRAC, and retrying..."
                    )
                    # Clear virtual media again
                    self._ensure_vm_cleared()
                    # Reset iDRAC to clear stale state
                    self._reset_idrac()
                    continue

                # Final attempt failed or non-reachability error
                # Include the original iDRAC error response for clarity
                raise LisaException(
                    f"Failed to insert virtual media from '{iso_http_url}' "
                    f"after {attempt} attempt(s). Ensure the iDRAC can reach this "
                    f"URL and the file exists. iDRAC error: {error_msg}"
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
        if response.dict["Attributes"]["SerialCapture.1.Enable"] == "Disabled":
            response = self.redfish_instance.patch(
                "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes",
                body={"Attributes": {"SerialCapture.1.Enable": "Enabled"}},
            )
        response = self.redfish_instance.get(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes"
        )
        if response.dict["Attributes"]["SerialCapture.1.Enable"] == "Enabled":
            self._log.debug("Serial console enabled successfully.")
        else:
            raise LisaException("Failed to enable serial console.")
        self.logout()

    def _clear_serial_console_log(self) -> None:
        response = self.redfish_instance.get(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes"
        )
        if response.dict["Attributes"]["SerialCapture.1.Enable"] == "Disabled":
            self._log.debug("Serial console is already disabled. No need to clear log.")
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/SerialInterfaces"
            "/Serial.1/Actions/Oem/DellSerialInterface.SerialDataClear",
            body={},
        )
        self._wait_for_completion(response)
