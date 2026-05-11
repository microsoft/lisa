# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import shlex
from pathlib import Path
from typing import Any, Optional

from lisa import features
from lisa.tools import Cat
from lisa.util import LisaException

from .context import get_node_context
from .schema import OPENVMM_SERIAL_MODE_FILE, OPENVMM_SERIAL_MODE_STDERR


class SerialConsole(features.SerialConsole):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        node_context = get_node_context(self._node)
        host_node = node_context.host
        if not host_node:
            raise LisaException(
                f"OpenVMM guest '{self._node.name}' does not have a host node "
                "recorded for serial console collection. Verify the guest was "
                "provisioned by the OpenVMM orchestrator."
            )

        runbook = getattr(self._node, "runbook", None)
        serial_mode = getattr(
            getattr(runbook, "serial", None), "mode", OPENVMM_SERIAL_MODE_FILE
        )
        console_log_file_path = node_context.console_log_file_path
        if serial_mode == OPENVMM_SERIAL_MODE_STDERR:
            console_log_file_path = node_context.launcher_stderr_log_file_path

        if not console_log_file_path:
            raise LisaException(
                f"OpenVMM guest '{self._node.name}' does not have a serial console "
                "log path. Verify OpenVMM launch completed before checking panic."
            )

        log = host_node.tools[Cat].read(
            shlex.quote(console_log_file_path),
            force_run=True,
            no_debug_log=True,
        )
        log = re.sub("\x1b\\[[0-9;]*[mGKF]", "", log)
        return log.encode("utf-8")
