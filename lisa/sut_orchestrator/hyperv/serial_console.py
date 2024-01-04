# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import Path, PurePath, PureWindowsPath

from lisa import RemoteNode, features
from lisa.tools import PowerShell

from .context import get_node_context


class SerialConsole(features.SerialConsole):
    def _get_console_log(self, saved_path: Path | None) -> bytes:
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
    TASK_PATH = "\\LISAHvPlatform\\"

    def __init__(self, server_node: RemoteNode) -> None:
        self._server = server_node
        local_script_path = Path(__file__).parent.joinpath("serial_console_helper.ps1")
        self._script_path = server_node.working_path / "serial_console_helper.ps1"
        server_node.shell.copy(
            local_script_path,
            self._script_path,
        )

    def start_logging(self, pipe_name: str, log_path: PureWindowsPath) -> None:
        task_name = f"task_{pipe_name}"
        self._server.tools[PowerShell].run_cmdlet(
            f'$action = New-ScheduledTaskAction -Execute "powershell.exe" '
            f'-Argument "-file {self._script_path} {pipe_name} {log_path}"; '
            f"$task = New-ScheduledTask -Action $action; "
            f"Register-ScheduledTask {task_name} -InputObject $task "
            f"-TaskPath {self.TASK_PATH}; "
            f"Start-ScheduledTask -TaskPath {self.TASK_PATH} -TaskName {task_name};",
            force_run=True,
        )

    def stop_logging(self, pipe_name: str) -> None:
        task_name = f"task_{pipe_name}"
        self._server.tools[PowerShell].run_cmdlet(
            f"Unregister-ScheduledTask -TaskPath {self.TASK_PATH} "
            f"-TaskName {task_name} -Confirm:$false",
            force_run=True,
        )
