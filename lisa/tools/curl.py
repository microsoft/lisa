# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import PurePath
from typing import Optional, cast

from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException
from lisa.util.process import ExecutableResult


class Curl(Tool):
    # curl 7.68.0 (x86_64-pc-linux-gnu)
    _version_pattern = re.compile(
        r"curl (?P<major>\d+).(?P<minor>(\d+)).(?P<patch>(\d+)) ", re.M
    )

    @property
    def command(self) -> str:
        return "curl"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        try:
            posix_os.install_packages("curl")
        except Exception as e:
            self._log.debug(f"failed to install curl: {e}")
        return self._check_exists()

    def fetch(
        self,
        url: str,
        arg: str,
        execute_arg: str,
        sudo: bool = False,
        shell: bool = False,
        cwd: Optional[PurePath] = None,
        expected_exit_code: Optional[int] = 0,
    ) -> ExecutableResult:
        err_msg = "curl fetch failed"
        cmd_arg = f" {arg} {url}"
        if execute_arg:
            cmd_arg = f"{cmd_arg} | sh {execute_arg}"
        result = self.run(
            cmd_arg,
            expected_exit_code=expected_exit_code,
            expected_exit_code_failure_message=err_msg,
            sudo=sudo,
            cwd=cwd,
            shell=shell,
        )
        return result

    def get_version(
        self,
        sudo: bool = False,
        shell: bool = False,
        cwd: Optional[PurePath] = None,
    ) -> VersionInfo:
        err_msg = "curl get_version failed"
        output = self.run(
            " --version",
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
            sudo=sudo,
            cwd=cwd,
            shell=shell,
        ).stdout

        matched_version = self._version_pattern.match(output)
        if matched_version:
            major = matched_version.group("major")
            minor = matched_version.group("minor")
            patch = matched_version.group("patch")
            return VersionInfo(int(major), int(minor), int(patch))
        raise LisaException("fail to get curl version")
