# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any, Optional, Type, cast

from lisa import features, schema
from lisa.environment import Environment
from lisa.node import Node
from lisa.node import quick_connect
from lisa.platform_ import Platform
from lisa.schema import FeatureSettings
from lisa.util import LisaException

from ..context import get_node_context
from ..platform_ import BareMetalPlatform
from ..schema import RackManagerClientSchema, RackManagerSchema
from .cluster import Cluster

SERIAL_LOGIN_TIMEOUT = 300


class RackManagerSerialConsole(features.SerialConsole):
    def __init__(
        self, settings: FeatureSettings, node: Node, platform: Platform
    ) -> None:
        super().__init__(settings, node, platform)
        self._process: Any = None
        self._username = ""
        self._password = ""

    def read(self) -> str:
        return self._get_console_log(saved_path=None).decode("utf-8", errors="ignore")

    def write(self, data: str) -> None:
        self._login()
        self._process.input(f"{data}\n")

    def close(self) -> None:
        if self._process:
            self._process.kill()

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        self._process.wait_output("", timeout=1, error_on_missing=False, interval=0.1)
        output = self._process.log_buffer.getvalue()
        return output if isinstance(output, bytes) else output.encode("utf-8")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        platform = cast(BareMetalPlatform, self._platform)
        cluster = cast(RackManager, platform.cluster)
        cluster.connect_to_rack_manager()

        context = get_node_context(self._node)
        client = cast(RackManagerClientSchema, context.client)
        assert (
            client.management_port is not None and client.management_port >= 0
        ), "management_port is required for rackmanager serial console"
        assert client.connection, "client connection is required for serial login"

        self._process = cluster.rm_node.execute_async(
            f"start serial session -i {client.management_port}"
        )

        self._username = client.connection.username
        self._password = client.connection.password

    def _login(self) -> None:
        current_output = self._get_console_log(saved_path=None).decode(
            "utf-8", errors="ignore"
        )
        current_prompt = current_output.rstrip()
        if current_prompt.endswith(("$", "#")):
            return

        if not current_prompt.lower().endswith("login:"):
            login_found = self._process.wait_output(
                "login:",
                timeout=SERIAL_LOGIN_TIMEOUT,
                error_on_missing=False,
                interval=1,
                delta_only=True,
            )
            if not login_found:
                raise LisaException("serial console login prompt was not found")

        self._process.input(f"{self._username}\n")
        password_found = self._process.wait_output(
            "Password:",
            timeout=10,
            error_on_missing=False,
            interval=0.5,
            delta_only=True,
        )
        if password_found:
            self._process.input(f"{self._password}\n")

        # Some serial consoles don't present a standard '$'/'#' prompt reliably.
        # Treat a repeated login prompt as authentication failure; otherwise continue.
        login_retry = self._process.wait_output(
            "login:",
            timeout=3,
            error_on_missing=False,
            interval=0.5,
            delta_only=True,
        )
        if login_retry:
            raise LisaException("serial console login failed and returned to login prompt")


class RackManagerStartStop(features.StartStop):
    def init_rack_manager(self) -> None:
        platform: BareMetalPlatform = self._platform  # type: ignore
        self.cluster: RackManager = platform.cluster  # type: ignore

    def _stop(
        self, wait: bool = True, state: features.StopState = features.StopState.Shutdown
    ) -> None:
        if state == features.StopState.Hibernate:
            raise NotImplementedError(
                "baremetal orchestrator does not support hibernate stop"
            )
        self.init_rack_manager()
        self.cluster.reset("off")

    def _start(self, wait: bool = True) -> None:
        self.init_rack_manager()
        self.cluster.reset("on")

    def _restart(self, wait: bool = True) -> None:
        self.init_rack_manager()
        self.cluster.reset("reset")


class RackManager(Cluster):
    def __init__(self, runbook: RackManagerSchema, **kwargs: Any) -> None:
        super().__init__(runbook, **kwargs)
        self.rm_runbook: RackManagerSchema = self.runbook

    @classmethod
    def type_name(cls) -> str:
        return "rackmanager"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RackManagerSchema

    def get_start_stop(self) -> Type[features.StartStop]:
        return RackManagerStartStop

    def get_serial_console(self) -> Type[features.SerialConsole]:
        return RackManagerSerialConsole

    def connect_to_rack_manager(self) -> None:
        assert self.rm_runbook.connection, "connection is required for rackmanager"
        self.rm_runbook.connection.name = "rackmanager"
        self.rm_node = quick_connect(
            self.rm_runbook.connection, logger_name="rackmanager"
        )

    def deploy(self, environment: Environment) -> Any:
        self.reset("off")
        self.reset("on")

    def reset(self, operation: str) -> None:
        self.connect_to_rack_manager()
        assert self.rm_runbook.client, "client is required for rackmanager"
        for client in self.rm_runbook.client:
            assert (
                client.management_port
            ), "management_port is required for rackmanager client"
            self.rm_node.execute(f"set system {operation} -i {client.management_port}")
        self._log.debug(f"client has been {operation} successfully")
