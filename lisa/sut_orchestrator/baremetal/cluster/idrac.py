# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import time
import xml.etree.ElementTree as ETree
from pathlib import Path
from typing import Any, Optional, Type

import redfish
from assertpy import assert_that

from lisa import features, schema
from lisa.environment import Environment
from lisa.util import LisaException, check_till_timeout
from lisa.util.perf_timer import create_timer

from ..platform_ import BareMetalPlatform
from ..schema import ClientSchema, ClusterSchema, IdracClientSchema, IdracSchema
from .cluster import Cluster


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
        self.login()
        self._eject_virtual_media()
        client_runbook: IdracClientSchema = self.client.get_extended_runbook(
            IdracClientSchema, "idrac"
        )
        assert client_runbook.iso_http_url, "iso_http_url is required for idrac client"
        self._change_boot_order_once("VCD-DVD")
        self.reset("ForceOff")
        self._insert_virtual_media(client_runbook.iso_http_url)
        self.reset("On", force_run=True)
        self.logout()

    def cleanup(self) -> None:
        self.login()
        self._clear_serial_console_log()
        self.logout()

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

    def _wait_for_completion(self, response: Any, timeout: int = 600) -> None:
        if response.is_processing:
            task = response.monitor(self.redfish_instance)
            timer = create_timer()
            while task.is_processing and timer.elapsed(False) < timeout:
                retry_time = task.retry_after
                time.sleep(retry_time if retry_time else 5)
                task = response.monitor(self.redfish_instance)

        if response.status not in [200, 202, 204]:
            raise LisaException("Failed to complete task! - status:", response.status)

    def _insert_virtual_media(self, iso_http_url: str) -> None:
        self._log.debug("Inserting virtual media...")
        body = {"Image": iso_http_url}
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD/Actions/"
            "VirtualMedia.InsertMedia",
            body=body,
        )
        self._wait_for_completion(response)
        self._log.debug("Inserting virtual media completed...")

    def _eject_virtual_media(self) -> None:
        self._log.debug("Ejecting virtual media...")
        response = self.redfish_instance.post(
            "/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD/Actions/"
            "VirtualMedia.EjectMedia",
            body={},
        )

        # Ignore return on failure as it is ok if no media was attached
        if response.status in [200, 202, 204]:
            self._wait_for_completion(response)

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
