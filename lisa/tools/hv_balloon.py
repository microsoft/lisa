# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from lisa.executable import Tool
from lisa.util import LisaException


@dataclass
class HvBalloonStats:
    host_version: str = ""
    capabilities: List[str] = field(default_factory=list)
    state: str = ""
    page_size: int = 0
    pages_added: int = 0
    pages_onlined: int = 0
    pages_ballooned: int = 0
    total_pages_committed: int = 0
    max_dynamic_page_count: int = 0
    raw: str = ""

    @property
    def net_pages_transaction(self) -> int:
        return self.pages_added - self.pages_ballooned


class HvBalloon(Tool):
    _DEBUGFS_PATH: str = "/sys/kernel/debug/hv-balloon"

    @property
    def command(self) -> str:
        return "cat"

    @property
    def can_install(self) -> bool:
        return False

    def ensure_debugfs_mounted(self) -> None:
        mount_check = self.node.execute(
            "mount | grep -i debugfs",
            sudo=True,
            shell=True,
            no_debug_log=True,
            no_info_log=True,
            no_error_log=True,
        )
        if mount_check.exit_code != 0:
            self.node.execute(
                "mount -t debugfs none /sys/kernel/debug",
                sudo=True,
                shell=True,
            )

    def get_metrics(self) -> HvBalloonStats:
        self.ensure_debugfs_mounted()
        raw = self._read_debugfs()
        if not raw:
            raise LisaException("Failed to read hv_balloon debugfs output")
        parsed = self._parse_output(raw)
        parsed.raw = raw
        return parsed

    def _read_debugfs(self) -> str:
        result = self.node.execute(
            f"cat {self._DEBUGFS_PATH}",
            sudo=True,
            shell=True,
            no_info_log=True,
            no_debug_log=True,
            no_error_log=True,
        )
        if result.exit_code == 0 and result.stdout:
            return result.stdout
        raise LisaException(
            "Unable to locate hv_balloon debugfs file. Last error: "
            f"{result.stderr or 'not found'}"
        )

    def _parse_output(self, raw: str) -> HvBalloonStats:
        stats = HvBalloonStats(raw=raw, capabilities=[])
        lines = raw.splitlines()
        data: Dict[str, str] = {}
        for line in lines:
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue
            key, value = stripped.split(":", maxsplit=1)
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            if not normalized_key:
                continue
            data[normalized_key] = value.strip()

        stats.host_version = data.get("host_version", "")
        capabilities_raw = data.get("capabilities", "")
        stats.capabilities = capabilities_raw.split() if capabilities_raw else []
        stats.state = self._parse_state(data.get("state", ""))
        stats.page_size = int(data.get("page_size", "0") or 0)
        stats.pages_added = int(data.get("pages_added", "0") or 0)
        stats.pages_onlined = int(data.get("pages_onlined", "0") or 0)
        stats.pages_ballooned = int(data.get("pages_ballooned", "0") or 0)
        stats.total_pages_committed = int(data.get("total_pages_committed", "0") or 0)
        stats.max_dynamic_page_count = int(data.get("max_dynamic_page_count", "0") or 0)
        return stats

    def _parse_state(self, value: str) -> str:
        if not value:
            return ""
        match = re.search(r"\(([^)]+)\)", value)
        if match:
            return match.group(1)
        return value.strip()
