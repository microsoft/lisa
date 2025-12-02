# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re
from typing import List, Type

from lisa.base_tools import Cat, Systemctl
from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.tools.journalctl import Journalctl
from lisa.util import LisaException, find_patterns_in_lines, get_matched_str

from .git import Git
from .grep import Grep
from .ls import Ls
from .make import Make


class HibernationSetup(Tool):
    _repo = "https://github.com/microsoft/hibernation-setup-tool"
    # [  159.967060] PM: hibernation entry
    _entry_pattern = "hibernation entry"
    # [   22.813227] PM: hibernation exit
    _exit_pattern = "hibernation exit"
    # [  159.898723] hv_utils: Hibernation request received
    _received_pattern = "Hibernation request received"
    # [  159.898806] hv_utils: Sent hibernation uevent
    _uevent_pattern = "Sent hibernation uevent"

    # hibernation-setup-tool: ERROR: System needs a swap area of 322170 MB;
    # but only has 294382 MB free space on device
    _insufficient_swap_space_pattern = re.compile(
        r"hibernation-setup-tool: ERROR: System needs a swap area of \d+ MB; "
        r"but only has \d+ MB free space on device",
        re.MULTILINE,
    )

    # Defrag size is larger than filesystem's free space
    _defrag_space_error_pattern = re.compile(
        r"Defrag size is larger than filesystem's free space",
        re.MULTILINE,
    )

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
        result = self.run(sudo=True)

        # Analyze stdout for error patterns first
        self._analyze_stdout_for_errors(result.stdout)

        # If no errors found in stdout but exit code is non-zero, raise generic failure
        if result.exit_code != 0:
            raise LisaException(
                f"hibernation-setup-tool failed with exit code {result.exit_code}"
            )

    def check_entry(self) -> int:
        return self._check(self._entry_pattern)

    def check_exit(self) -> int:
        return self._check(self._exit_pattern)

    def check_received(self) -> int:
        return self._check(self._received_pattern)

    def check_uevent(self) -> int:
        return self._check(self._uevent_pattern)

    def _analyze_stdout_for_errors(self, stdout: str) -> None:
        # Check for insufficient swap space error
        swap_error = get_matched_str(stdout, self._insufficient_swap_space_pattern)
        if swap_error:
            raise LisaException(f"Hibernation setup failed: {swap_error}")

        # Check for defrag space error
        defrag_error = get_matched_str(stdout, self._defrag_space_error_pattern)
        if defrag_error:
            raise LisaException(
                f"Hibernation setup failed: {defrag_error}. "
                "Please increase osdisk_size_in_gb."
            )

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

    def _check(self, pattern: str) -> int:
        """
        Check for pattern matches in log files using grep for efficiency.
        This avoids reading large log files entirely which can cause timeouts.
        """
        grep = self.node.tools[Grep]
        ls = self.node.tools[Ls]

        # Determine which log file to use
        if ls.path_exists("/var/log/syslog", sudo=True):
            log_file = "/var/log/syslog"
        elif ls.path_exists("/var/log/messages", sudo=True):
            log_file = "/var/log/messages"
        else:
            # Fall back to journalctl for systems without traditional log files
            journalctl = self.node.tools[Journalctl]
            log_output = journalctl.first_n_logs_from_boot(no_of_lines=0)
            # Compile pattern only when needed for journalctl path
            compiled_pattern = re.compile(pattern)
            matched_lines = find_patterns_in_lines(log_output, [compiled_pattern])
            if not matched_lines:
                return 0
            return len(matched_lines[0])

        return grep.count(
            pattern=pattern,
            file=log_file,
            sudo=True,
            no_debug_log=True,
            force_run=True,
        )
