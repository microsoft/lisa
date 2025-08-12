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

        # Try to read from the libvirt console log file first
        # This should contain the complete console output from boot time
        console_log_path = node_context.console_log_file_path
        
        try:
            with open(console_log_path, mode="rb") as file:
                log_bytes = file.read()
                
            # If we got substantial content, use it
            if len(log_bytes) > 100:  # More than just login prompt
                # Remove ANSI control codes from the text
                log_text = log_bytes.decode("utf-8", errors="ignore")
                log_text = re.sub("\x1b\\[[0-9;]*[mGKF]", "", log_text)
                return log_text.encode("utf-8")
                
        except (FileNotFoundError, PermissionError):
            # Log file doesn't exist or can't be read, fall back to old method
            pass

        # Fallback to the original method (real-time console stream)
        # This will only capture output from after the logger was attached
        try:
            with open(
                node_context.console_log_file_path, mode="r", encoding="utf-8"
            ) as file:
                log = file.read()

            # Remove ANSI control codes.
            log = re.sub("\x1b\\[[0-9;]*[mGKF]", "", log)

            log_bytes = log.encode("utf-8")
            return log_bytes
            
        except (FileNotFoundError, PermissionError):
            # If both methods fail, return empty bytes
            return b""
