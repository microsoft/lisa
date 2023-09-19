# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
import xml.etree.ElementTree as ETree
from typing import Any, Type

import redfish  # type: ignore
from assertpy import assert_that

from lisa import features, schema
from lisa.environment import Environment
from lisa.util import LisaException, check_till_timeout
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer

from ..platform_ import BareMetalPlatform
from ..schema import ClusterSchema, IdracSchema
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
        if self.cluster.get_power_state() == "Off":
            self._log.debug("System is already off.")
            return
        self.cluster.reset("ForceOff")
        self._logout()

    def _start(self, wait: bool = True) -> None:
        self._login()
        if self.cluster.get_power_state() == "On":
            self._log.debug("System is already powered on.")
            return
        self.cluster.reset("On")
        self._logout()

    def _restart(self, wait: bool = True) -> None:
        self._login()
        self.cluster.reset("ForceRestart")
        self._logout()


class Idrac(Cluster):
    def __init__(self, runbook: ClusterSchema) -> None:
        super().__init__(runbook)
        self.idrac_runbook: IdracSchema = self.runbook
        self._log = get_logger("idrac", self.__class__.__name__)
        assert_that(len(self.idrac_runbook.client)).described_as(
            "only one client is supported for idrac, don't specify more than one client"
        ).is_equal_to(1)

        self.client = self.idrac_runbook.client[0]

    @classmethod
    def type_name(cls) -> str:
        return "idrac"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return IdracSchema

    def get_start_stop(self) -> Type[features.StartStop]:
        return IdracStartStop

    def deploy(self, environment: Environment) -> Any:
        self.login()
        self._eject_virtual_media()
        assert self.client.iso_http_url, "iso_http_url is required for idrac client"
        if self.get_power_state() == "Off":
            self._log.debug("System is already off.")
        else:
            self.reset("ForceOff")
        self._insert_virtual_media(self.client.iso_http_url)
        self._change_boot_order_once("VCD-DVD")
        check_till_timeout(
            lambda: self.get_power_state() == "Off",
            timeout_message="wait for client into 'Off' state",
        )
        self.reset("On")
        check_till_timeout(
            lambda: self.get_power_state() == "On",
            timeout_message="wait for client into 'On' state",
        )
        self.logout()

    def reset(self, operation: str) -> None:
        body = {"ResetType": operation}
        response = self.redfish_instance.post(
            "/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset",
            body=body,
        )
        self._wait_for_completion(response)
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
