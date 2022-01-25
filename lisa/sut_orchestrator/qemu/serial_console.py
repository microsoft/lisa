# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import Path
from typing import Any, Optional

from lisa import features

from .context import get_node_context


# Implements the SerialConsole feature.
class SerialConsole(features.SerialConsole):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        node_context = get_node_context(self._node)

        # Open the log file.
        # This file is simultaneously being written to by QemuConsoleLogger.
        with open(
            node_context.console_log_file_path, mode="r", encoding="utf-8"
        ) as file:
            log = file.read()

        # Remove ANSI control codes.
        log = re.sub("\x1b\\[[0-9;]*[mGKF]", "", log)

        log_bytes = log.encode("utf-8")
        return log_bytes
