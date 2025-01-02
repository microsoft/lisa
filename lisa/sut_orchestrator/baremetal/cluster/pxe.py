# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any, Optional, Type, cast

from lisa import features
from lisa.environment import Environment
from lisa.features.serial_console import SerialConsole
from lisa.node import Node, RemoteNode, quick_connect
from lisa.platform_ import Platform
from lisa.schema import FeatureSettings
from lisa.util import LisaException
from lisa.util.logger import Logger

from .. import schema
from ..context import get_node_context
from .cluster import Cluster


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
            "Unable to open connection", timeout=1, error_on_missing=False, interval=0.1
        )
        if found_error:
            process.kill()
            raise LisaException(f"failed to connect serial console: {serial_port}")

        # entering to make sure connection is established, avoid it's too fast
        # to send content
        process.input("\n")
        process.wait_output("\n", timeout=1, interval=0.1)

        self._process = process
        self._log.debug("connected to serial console: {serial_port}")


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
