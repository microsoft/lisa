# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from functools import partial
from pathlib import Path, PurePath, PureWindowsPath
from typing import Optional

from lisa import RemoteNode, features
from lisa.tools import PowerShell
from lisa.util.logger import Logger
from lisa.util.parallel import TaskManager, run_in_parallel_async

from .context import get_node_context


class SerialConsole(features.SerialConsole):
    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        node = self._node
        node_ctx = get_node_context(node)

        assert node_ctx.server_node, "server node is not set"

        vm_name = node_ctx.vm_name
        server_node = node_ctx.server_node
        console_log_path = node_ctx.console_log_path
        console_log_local_path = server_node.local_log_path / f"{vm_name}-console.log"
        server_node.shell.copy_back(console_log_path, PurePath(console_log_local_path))

        with open(console_log_local_path, mode="r", encoding="utf-8") as f:
            log = f.read()

        # Remove ANSI control codes.
        log = re.sub("\x1b\\[[0-9;]*[mGKF]", "", log)

        log_bytes = log.encode("utf-8")
        return log_bytes


class SerialConsoleLogger:
    SERIAL_LOGGER_SCRIPT = "serial_console_logger.ps1"

    def __init__(self, server_node: RemoteNode) -> None:
        self._server = server_node
        local_script_path = Path(__file__).parent.joinpath(self.SERIAL_LOGGER_SCRIPT)
        self._script_path = server_node.working_path / self.SERIAL_LOGGER_SCRIPT
        server_node.shell.copy(
            local_script_path,
            self._script_path,
        )

    def start_logging(
        self, pipe_name: str, log_path: PureWindowsPath, logger: Logger
    ) -> TaskManager[None]:
        def _ignore_result(result: None) -> None:
            pass

        def _run_logger_script(
            server: RemoteNode, script_path: str, pipe_name: str, out_file: str
        ) -> None:
            server.tools[PowerShell].run_cmdlet(
                f'{script_path} "{pipe_name}" "{out_file}"',
                timeout=36000,
                fail_on_error=True,
            )

        return run_in_parallel_async(
            [
                partial(
                    _run_logger_script,
                    self._server,
                    self._script_path,
                    pipe_name,
                    log_path,
                )
            ],
            _ignore_result,
            logger,
        )
