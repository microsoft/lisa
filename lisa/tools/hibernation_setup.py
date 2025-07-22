# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re
from typing import List, Pattern, Type

from lisa.base_tools import Cat, Systemctl
from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.tools.journalctl import Journalctl
from lisa.util import find_patterns_in_lines, get_matched_str

from .git import Git
from .ls import Ls
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

    """
    The below shows an example output of `filefrag -v /hibfile.sys`
    We are interested in the physical offset of the hibfile.

    Filesystem type is: ef53
    File size of /hibfile is 1048576 (256 blocks of 4096 bytes)
    ext:     logical_offset:        physical_offset: length:   expected: flags:
    0:        0..      255:    123456..   123711:    256:             last,unwritten,eof
    /hibfile: 1 extent found
    """
    _hibsys_resume_offset_pattern = re.compile(
        r"^\s*\d+:\s+\d+\.\.\s+\d+:\s+(\d+)\.\.", re.MULTILINE
    )

    _cmdline_resume_offset_pattern = re.compile(r"resume_offset=(\d+)")

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
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to start",
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

    def get_hibernate_resume_offset_from_hibfile(self) -> str:
        filefrag_hibfile = self.node.execute(
            "filefrag -v /hibfile.sys", sudo=True
        ).stdout
        offset = get_matched_str(filefrag_hibfile, self._hibsys_resume_offset_pattern)
        return offset

    def get_hibernate_resume_offset_from_cmd(self) -> str:
        cmdline = self.node.tools[Cat].read("/proc/cmdline")
        offset = get_matched_str(cmdline, self._cmdline_resume_offset_pattern)
        return offset

    def get_hibernate_resume_offset_from_sys_power(self) -> str:
        cat = self.node.tools[Cat]
        offset = cat.read("/sys/power/resume_offset", force_run=True, sudo=True)
        return offset

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
        ls = self.node.tools[Ls]
        if ls.path_exists("/var/log/syslog", sudo=True):
            log_output = cat.read("/var/log/syslog", force_run=True, sudo=True)
        elif ls.path_exists("/var/log/messages", sudo=True):
            log_output = cat.read("/var/log/messages", force_run=True, sudo=True)
        else:
            journalctl = self.node.tools[Journalctl]
            log_output = journalctl.first_n_logs_from_boot(no_of_lines=0)
        matched_lines = find_patterns_in_lines(log_output, [pattern])
        if not matched_lines:
            return 0
        return len(matched_lines[0])
