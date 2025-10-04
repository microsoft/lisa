# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path, PurePath
from typing import Optional

from lisa import RemoteNode, features
from lisa.tools import PowerShell
from lisa.util import filter_ansi_escape
from lisa.util.logger import Logger, get_logger
from lisa.util.process import Process

from .context import get_node_context


class SerialConsole(features.SerialConsole):
    def _decode_without_bom(self, data: bytes, vm_name: str) -> str:
        """
        Decode console log data without BOM using fallback chain.
        Tries: UTF-8 -> UTF-16-LE -> CP1252 -> UTF-8 with replacement
        """
        encodings = ["utf-8", "utf-16-le", "cp1252"]

        for encoding in encodings:
            try:
                return data.decode(encoding, errors="strict")
            except UnicodeDecodeError:
                continue

        # Last resort: decode with replacement to avoid crash
        log = data.decode("utf-8", errors="replace")
        repl = log.count("\ufffd")
        if repl:
            _logger = get_logger("serial_console")
            _logger.debug(
                f"Console log for VM '{vm_name}' required {repl} "
                f"replacement characters during decode "
                f"(possible non-UTF encoding or binary content)."
            )
        return log

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        node = self._node
        node_ctx = get_node_context(node)

        assert node_ctx.host, "host node is not set"

        vm_name = node_ctx.vm_name
        server_node = node_ctx.host
        console_log_path = node_ctx.console_log_path
        console_log_local_path = server_node.local_log_path / f"{vm_name}-console.log"
        server_node.shell.copy_back(console_log_path, PurePath(console_log_local_path))

        # Read bytes first so we can honor BOMs and handle non-UTF8 logs
        # from Windows hosts.
        data = console_log_local_path.read_bytes()

        # Detect BOMs and decode accordingly
        if data.startswith(b"\xef\xbb\xbf"):
            # UTF-8 with BOM
            log = data[3:].decode("utf-8", errors="strict")
        elif data.startswith(b"\xff\xfe"):
            # UTF-16 LE (typical for Windows PowerShell 5.x)
            log = data[2:].decode("utf-16-le", errors="strict")
        elif data.startswith(b"\xfe\xff"):
            # UTF-16 BE
            log = data[2:].decode("utf-16-be", errors="strict")
        else:
            # No BOM - try different encodings with fallback chain
            log = self._decode_without_bom(data, vm_name)

        log = filter_ansi_escape(log)

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
        self, pipe_name: str, log_path: PurePath, logger: Logger
    ) -> Process:
        return self._server.tools[PowerShell].run_cmdlet_async(
            f'{self._script_path} "{pipe_name}" "{log_path}"', force_run=True
        )
