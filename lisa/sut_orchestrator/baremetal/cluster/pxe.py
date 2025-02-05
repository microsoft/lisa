# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from time import sleep
from typing import Any, Optional, Type, cast

import requests

from lisa import features
from lisa.environment import Environment
from lisa.features import SerialConsole, StartStop
from lisa.node import Node, RemoteNode, quick_connect
from lisa.platform_ import Platform
from lisa.schema import FeatureSettings
from lisa.util import LisaException
from lisa.util.logger import Logger

from .. import schema
from ..context import get_node_context
from .cluster import Cluster

REQUEST_TIMEOUT = 3
POWER_DOWN_DELAY = 3


class RemoteComSerialConsole(features.SerialConsole):
    def __init__(
        self, settings: FeatureSettings, node: Node, platform: Platform
    ) -> None:
        super().__init__(settings, node, platform)

    def close(self) -> None:
        self._process.kill()
        self._log.debug("serial console is closed.")

    def write(self, data: str) -> None:
        self._process.input(f"{data}\n")

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        # To get complete log of serial console, it is required to flush
        # the output buffer of serial console before accessing its serial
        # log_buffer. Here empty string "" is passed in wait_output, which
        # is used to just trigger the flush of the serial console buffer.
        self._process.wait_output(
            "",
            timeout=1,
            error_on_missing=False,
            interval=0.1,
        )
        return self._process.log_buffer.getvalue().encode("utf-8")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

        context = get_node_context(self._node)
        pxe_cluster = cast(schema.PxeCluster, context.cluster)
        assert pxe_cluster.serial_console, "serial_console is not defined"

        connection = pxe_cluster.serial_console.get_extended_runbook(
            schema.RemoteComSerialConsoleServer
        ).connection
        assert connection, "connection is required for windows remote com"
        serial_node = quick_connect(
            connection, logger_name="serial", parent_logger=self._log
        )

        serial_console = pxe_cluster.serial_console.get_extended_runbook(
            schema.RemoteComSerialConsoleServer
        )

        self._plink_path = serial_node.get_pure_path("plink")
        if serial_console.plink_path:
            # Use remote pure path, because the remote OS may be different with
            # LISA running OS.
            self._plink_path = serial_console.plink_path / self._plink_path

        self._serial_node = cast(RemoteNode, serial_node)
        # connect to serial console server from beginning to collect all log.
        self._connect()

    def _connect(self) -> None:
        context = get_node_context(self._node)

        client_runbook = cast(schema.PxeClient, context.client)
        serial_client_runbook = client_runbook.serial_console
        assert serial_client_runbook, "serial_console is not defined"
        serial_port = serial_client_runbook.port

        pxe_cluster = cast(schema.PxeCluster, context.cluster)
        assert pxe_cluster.serial_console, "serial_console is not defined"
        server_runbook = pxe_cluster.serial_console.get_extended_runbook(
            schema.RemoteComSerialConsoleServer
        )

        self._log.debug(f"connecting to serial console: {serial_port}")
        # Note: the leading whitespace " COM1", which is before the com port, is
        # required to avoid plink bug. If there is no leading whitespace, plink
        # will fail to open com, because the name is recognized like "\.\\" not
        # "\\.\COM1".
        process = self._serial_node.execute_async(
            f'{self._plink_path} -serial " {serial_port}" '
            f"-sercfg {server_runbook.bps},8,n,1,N"
        )

        found_error = process.wait_output(
            "Unable to open connection",
            timeout=1,
            error_on_missing=False,
            interval=0.1,
            delta_only=True,
        )
        if found_error:
            process.kill()
            raise LisaException(f"failed to connect serial console: {serial_port}")

        # entering to make sure connection is established, avoid it's too fast
        # to send content
        process.input("\n")
        process.wait_output("\n", timeout=1, interval=0.1)

        self._process = process
        self._log.debug(f"connected to serial console: {serial_port}")


class Ip9285StartStop(features.StartStop):
    def __init__(
        self, settings: FeatureSettings, node: Node, platform: Platform
    ) -> None:
        super().__init__(settings, node, platform)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

        context = get_node_context(self._node)
        pxe_cluster = cast(schema.PxeCluster, context.cluster)
        assert pxe_cluster.start_stop, "start_stop is not defined"

        ip_power_runbook = pxe_cluster.start_stop.get_extended_runbook(schema.Ip9285)

        self._request_cmd = (
            f"http://{ip_power_runbook.host}/set.cmd?"
            f"user={ip_power_runbook.username}+pass="
            f"{ip_power_runbook.password}+cmd="
            f"setpower+P6{ip_power_runbook.ctrl_port}"
        )

    def _set_ip_power(self, power_cmd: str) -> None:
        response = requests.get(power_cmd, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        self._log.debug(f"Command {power_cmd} done in set_ip_power")

    def _stop(
        self,
        wait: bool = True,
        state: features.StopState = features.StopState.Shutdown,
    ) -> None:
        request_off = f"{self._request_cmd}=0"
        self._set_ip_power(request_off)
        # To make sure power-off is fully settled down, it is recommended
        # to wait a short time before power-on is triggered. Local tests showed
        # 1s is actually good enough to get a stable power-off status, here
        # 3s is used in order to garantee power-off is successfully executed.
        sleep(POWER_DOWN_DELAY)

    def _start(self, wait: bool = True) -> None:
        request_on = f"{self._request_cmd}=1"
        self._set_ip_power(request_on)

    def _restart(self, wait: bool = True) -> None:
        self._stop()
        self._start()


class Pxe(Cluster):
    def __init__(self, runbook: schema.ClusterSchema, **kwargs: Any) -> None:
        super().__init__(runbook, **kwargs)
        self.runbook: schema.PxeCluster = self.runbook

    @classmethod
    def type_name(cls) -> str:
        return "pxe"

    @classmethod
    def type_schema(cls) -> Type[schema.PxeCluster]:
        return schema.PxeCluster

    def get_serial_console(self) -> Type[SerialConsole]:
        assert self.runbook.serial_console, "serial_console is not defined"
        if self.runbook.serial_console.type == "remote_com":
            return RemoteComSerialConsole
        else:
            raise NotImplementedError(
                f"serial console type {self.runbook.serial_console.type} "
                f"is not supported."
            )

    def get_start_stop(self) -> Type[StartStop]:
        assert self.runbook.start_stop, "start_stop is not defined"
        if self.runbook.start_stop.type == "Ip9285":
            return Ip9285StartStop
        else:
            raise NotImplementedError(
                f"start_stop type {self.runbook.start_stop.type} is not supported."
            )

    def deploy(self, environment: Environment) -> Any:
        # connect to serial console
        for node in environment.nodes.list():
            # start serial console to save all log
            _ = node.features[features.SerialConsole]

    def delete(self, environment: Environment, log: Logger) -> None:
        for node in environment.nodes.list():
            serial_console = node.features[features.SerialConsole]
            serial_console.close()

    def cleanup(self) -> None:
        super().cleanup()
