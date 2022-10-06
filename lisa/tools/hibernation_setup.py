# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re
from typing import List, Pattern, Type

from lisa.base_tools import Cat, Systemctl
from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.util import find_patterns_in_lines

from .git import Git
from .make import Make


class HibernationSetup(Tool):
    _repo = "https://github.com/microsoft/hibernation-setup-tool"
    # [  159.967060] PM: hibernation entry
    _entry_pattern = re.compile(r"^(.*hibernation entry.*)$", re.MULTILINE)
    # [   22.813227] PM: hibernation exit
    _exit_pattern = re.compile(r"^(.*hibernation exit.*)$", re.MULTILINE)
    # [  159.898723] hv_utils: Hibernation request received
    _received_pattern = re.compile(
        r"^(.*Hibernation request received.*)$", re.MULTILINE
    )
    # [  159.898806] hv_utils: Sent hibernation uevent
    _uevent_pattern = re.compile(r"^(.*Sent hibernation uevent.*)$", re.MULTILINE)

    @property
    def command(self) -> str:
        return "hibernation-setup-tool"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make]

    @property
    def can_install(self) -> bool:
        return True

    def start(self) -> None:
        self.run(
            sudo=True,
            timeout=300,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to start",
            force_run=True,
        )

    def check_entry(self) -> int:
        return self._check(self._entry_pattern)

    def check_exit(self) -> int:
        return self._check(self._exit_pattern)

    def check_received(self) -> int:
        return self._check(self._received_pattern)

    def check_uevent(self) -> int:
        return self._check(self._uevent_pattern)

    def hibernate(self) -> None:
        self.node.tools[Systemctl].hibernate()

    def _install(self) -> bool:
        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages(["glibc-devel", "kernel-headers", "binutils"])
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self._repo, tool_path)
        code_path = tool_path.joinpath("hibernation-setup-tool")
        make = self.node.tools[Make]
        make.make_install(code_path)
        return self._check_exists()

    def _check(self, pattern: Pattern[str]) -> int:
        cat = self.node.tools[Cat]
        log_output = ""
        if (self.node.execute("ls -lt /var/log/syslog", sudo=True)).exit_code == 0:
            log_output = cat.read("/var/log/syslog", force_run=True, sudo=True)
        if (self.node.execute("ls -lt /var/log/messages", sudo=True)).exit_code == 0:
            log_output = cat.read("/var/log/messages", force_run=True, sudo=True)
        matched_lines = find_patterns_in_lines(log_output, [pattern])
        if not matched_lines:
            return 0
        return len(matched_lines[0])
