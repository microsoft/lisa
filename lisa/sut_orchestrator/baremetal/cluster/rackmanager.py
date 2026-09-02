# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from pathlib import Path
from typing import Any, Optional, Type, cast

from lisa import features, schema
from lisa.environment import Environment
from lisa.node import Node, quick_connect
from lisa.platform_ import Platform
from lisa.schema import FeatureSettings
from lisa.util import LisaException

from ..context import get_node_context
from ..platform_ import BareMetalPlatform
from ..schema import RackManagerClientSchema, RackManagerSchema
from .cluster import Cluster

SERIAL_LOGIN_TIMEOUT = 300
SERIAL_PASSWORD_TIMEOUT = 10
SERIAL_LOGIN_RETRY_TIMEOUT = 3
SERIAL_PROMPT_WAKE_TIMEOUT = 5
SERIAL_PROMPT_WAKE_ATTEMPTS = 3


class RackManagerSerialConsole(features.SerialConsole):
    panic_ignorable_patterns = features.SerialConsole.panic_ignorable_patterns + [
        re.compile(r"^(.*firmware bug.*)$", re.MULTILINE | re.IGNORECASE),
    ]

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

    def _get_prompt_state(self, output_offset: int = 0) -> str:
        output = self._get_console_log(saved_path=None).decode("utf-8", errors="ignore")
        output = output[output_offset:]
        prompt = output.rstrip()
        if prompt.endswith(("$", "#")):
            return "shell"
        if prompt.lower().endswith("login:"):
            return "login"
        if prompt.lower().endswith("password:"):
            return "password"
        return "unknown" if prompt else "empty"

    def _wait_for_prompt_state(self, timeout: int, output_offset: int = 0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self._get_prompt_state(output_offset)
            if state in ("shell", "login", "password"):
                return state
        return self._get_prompt_state(output_offset)

    def _login(self) -> None:
        prompt_state = self._get_prompt_state()
        if prompt_state == "shell":
            return

        for _ in range(SERIAL_PROMPT_WAKE_ATTEMPTS):
            if prompt_state != "empty" and prompt_state != "unknown":
                break
            self._process.input("\n")
            prompt_state = self._wait_for_prompt_state(SERIAL_PROMPT_WAKE_TIMEOUT)

        if prompt_state == "shell":
            return
        if prompt_state in ("empty", "unknown"):
            prompt_state = self._wait_for_prompt_state(SERIAL_LOGIN_TIMEOUT)
        if prompt_state in ("empty", "unknown"):
            raise LisaException(
                "serial console produced no recognizable shell, login, or password "
                "prompt after wake attempts"
            )

        if prompt_state == "login":
            self._process.input(f"{self._username}\n")
            password_found = self._process.wait_output(
                "Password:",
                timeout=SERIAL_PASSWORD_TIMEOUT,
                error_on_missing=False,
                interval=0.5,
                delta_only=True,
            )
            if not password_found:
                raise LisaException("serial console password prompt was not found")
            prompt_state = "password"
        if prompt_state == "password":
            output_offset = len(
                self._get_console_log(saved_path=None).decode("utf-8", errors="ignore")
            )
            self._process.input(f"{self._password}\n")

        deadline = time.time() + SERIAL_LOGIN_RETRY_TIMEOUT
        while time.time() < deadline:
            output = self._get_console_log(saved_path=None).decode(
                "utf-8", errors="ignore"
            )
            if re.search(r"(?im)^.*login:\s*$", output[output_offset:]):
                raise LisaException(
                    "serial console login failed and returned to login prompt"
                )
            time.sleep(0.5)


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
        clients = self.rm_runbook.client
        assert clients, "client is required for rackmanager"

        iso_clients = [client for client in clients if client.iso_name]
        if not iso_clients:
            return

        self.connect_to_rack_manager()
        for client in iso_clients:
            management_port = client.management_port
            assert (
                management_port
            ), "management_port is required when rackmanager iso_name is set"
            self.rm_node.execute(
                f"set system boot -b 0 -m 1 -p 0 -i {management_port} -t 5"
            ).assert_exit_code()
            self.rm_node.execute(
                "set system remotedrive mount -b 0 -m 2 "
                f"-i {management_port} -n {client.iso_name}"
            ).assert_exit_code()
            self.rm_node.execute(
                f"set sys reset -i {management_port}"
            ).assert_exit_code()

    def reset(self, operation: str) -> None:
        self.connect_to_rack_manager()
        assert self.rm_runbook.client, "client is required for rackmanager"
        for client in self.rm_runbook.client:
            assert (
                client.management_port
            ), "management_port is required for rackmanager client"
            self.rm_node.execute(f"set system {operation} -i {client.management_port}")
        self._log.debug(f"client has been {operation} successfully")
