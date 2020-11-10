from pathlib import Path
from typing import Any, Optional

import requests

from lisa import features
from lisa.node import Node

from .common import get_compute_client, get_node_context, wait_operation


class AzureFeatureMixin:
    def _initialize_information(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._vm_name = node_context.vm_name
        self._resource_group_name = node_context.resource_group_name


class StartStop(AzureFeatureMixin, features.StartStop):
    def _stop(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_stop")

    def _start(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_start")

    def _restart(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_restart")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _execute(self, wait: bool, operator: str) -> Any:
        compute_client = get_compute_client(self._platform)
        operator_method = getattr(compute_client.virtual_machines, operator)
        result = operator_method(
            vm_name=self._vm_name, resource_group_name=self._resource_group_name
        )
        if wait:
            result = wait_operation(result)
        return result


class SerialConsole(AzureFeatureMixin, features.SerialConsole):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        compute_client = get_compute_client(self._platform)
        diagnostic_data = (
            compute_client.virtual_machines.retrieve_boot_diagnostics_data(
                resource_group_name=self._resource_group_name, vm_name=self._vm_name
            )
        )
        if saved_path:
            screenshot_name = saved_path.joinpath("serial_console.bmp")
            screenshot_response = requests.get(
                diagnostic_data.console_screenshot_blob_uri
            )
            with open(screenshot_name, mode="wb") as f:
                f.write(screenshot_response.content)

        log_response = requests.get(diagnostic_data.serial_console_log_blob_uri)

        return log_response.content
