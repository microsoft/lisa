# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from enum import Enum
from typing import Dict, List, Literal, Optional

from assertpy import assert_that
from semver import VersionInfo

from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.process import ExecutableResult

# Supported log facilities:
#     kern - kernel messages
#     user - random user-level messages
#     mail - mail system
#   daemon - system daemons
#     auth - security/authorization messages
#   syslog - messages generated internally by syslogd
#      lpr - line printer subsystem
#     news - network news subsystem

# Supported log levels (priorities):
#    emerg - system is unusable
#    alert - action must be taken immediately
#     crit - critical conditions
#      err - error conditions
#     warn - warning conditions
#   notice - normal but significant condition
#     info - informational
#    debug - debug-level messages


class LogLevel(Enum):
    EMERGENCY = "emerg"
    ALERT = "alert"
    CRITICAL = "crit"
    ERROR = "err"
    WARNING = "warn"
    NOTICE = "notice"
    INFO = "info"
    DEBUG = "debug"


def _get_log_levels(level: LogLevel) -> List[str]:
    values = []
    for level_ in LogLevel:
        values.append(level_.value)
        if level_ == level:
            break
    return values


class LogFacility(Enum):
    KERN = "kern"
    USER = "user"
    MAIL = "mail"
    DAEMON = "daemon"
    AUTH = "auth"
    SYSLOG = "syslog"
    LPR = "lpr"
    NEWS = "news"


class Dmesg(Tool):

    # meet any pattern will be considered as potential error line.
    __errors_patterns = [
        re.compile("Call Trace"),
        re.compile("rcu_sched self-detected stall on CPU"),
        re.compile("rcu_sched detected stalls on"),
        re.compile("BUG: soft lockup"),
    ]

    # [   3.191822] hv_vmbus: Hyper-V Host Build:18362-10.0-3-0.3294; Vmbus version:3.0
    # [   3.191822] hv_vmbus: Vmbus version:3.0
    __vmbus_version_pattern = re.compile(
        r"\[\s+\d+.\d+\]\s+hv_vmbus:.*Vmbus version:(?P<major>\d+).(?P<minor>\d+)"
    )

    @property
    def command(self) -> str:
        return "dmesg"

    def _check_exists(self) -> bool:
        return True

    def get_output(
        self,
        log_level: Optional[LogLevel] = None,
        log_facilities: Optional[List[LogFacility]] = None,
        force_run: bool = False,
    ) -> str:
        # validate and set log level and facility arguments if present
        if log_level:
            # get list of log levels up to the one we've selected
            log_levels = _get_log_levels(log_level)
            self.node.log.info(f"selected log levels: {log_levels}")
            parameters = "-l " + ",".join(log_levels)

        else:
            parameters = ""

        if log_facilities:
            # get str values from enum class
            log_facility = [x.value for x in log_facilities]
            parameters += " --facility=" + ",".join(log_facility)

        # run the command
        command_output = self._run(parameters, force_run=force_run)
        return command_output.stdout

    def check_kernel_errors(
        self,
        force_run: bool = False,
        throw_error: bool = True,
    ) -> str:
        command_output = self._run(force_run=force_run)
        command_output.assert_exit_code()
        matched_lines: List[str] = []
        for line in command_output.stdout.splitlines(keepends=False):
            for pattern in self.__errors_patterns:
                if pattern.search(line):
                    matched_lines.append(line)
                    # match one rule, so skip for other patterns
                    break
        result = "\n".join(matched_lines)
        if result:
            # log first line only, in case it's too long
            error_message = (
                f"dmesg error with {len(matched_lines)} lines, "
                f"first line: '{matched_lines[0]}'"
            )
            if throw_error:
                raise LisaException(error_message)
            else:
                self._log.debug(error_message)
        return result

    def get_vmbus_version(self) -> VersionInfo:
        result = self._run()
        result.assert_exit_code(
            message=f"exit code should be zero, but actually {result.exit_code}"
        )
        raw_vmbus_version = re.finditer(self.__vmbus_version_pattern, result.stdout)
        for vmbus_version in raw_vmbus_version:
            matched_vmbus_version = self.__vmbus_version_pattern.match(
                vmbus_version.group()
            )
            if matched_vmbus_version:
                major = matched_vmbus_version.group("major")
                minor = matched_vmbus_version.group("minor")
                self._log.info(f"vmbus version is {major}.{minor}")
                return VersionInfo(int(major), int(minor))
        raise LisaException("No find matched vmbus version in dmesg")

    def _run(self, parameters: str = "", force_run: bool = False) -> ExecutableResult:
        # sometime it need sudo, we can retry
        # so no_error_log for first time
        result = self.run(parameters=parameters, force_run=force_run, no_error_log=True)
        if result.exit_code != 0:
            # may need sudo
            result = self.run(parameters=parameters, sudo=True, force_run=force_run)
        self._cached_result = result
        return result
