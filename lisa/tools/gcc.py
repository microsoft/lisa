# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import cast

from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian, Fedora, Posix, Suse
from lisa.util import LisaException, UnsupportedDistroException


class Gcc(Tool):
    # gcc (Ubuntu 11.2.0-19ubuntu1) 11.2.0
    # gcc (GCC) 8.5.0 20210514 (Red Hat 8.5.0-10)
    _version_pattern = re.compile(
        r"gcc \(.*\) (?P<major>\d+).(?P<minor>(\d+)).(?P<patch>(\d+))", re.M
    )

    @property
    def command(self) -> str:
        return "gcc"

    @property
    def can_install(self) -> bool:
        return True

    def compile(
        self, filename: str, output_name: str = "", arguments: str = ""
    ) -> None:
        cmd = f"{arguments} {filename}"
        if output_name:
            cmd += f" -o {output_name} "
        self.run(cmd, shell=True, force_run=True)

    def get_version(self) -> VersionInfo:
        output = self.run(
            "--version",
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to get gcc dumpversion",
        ).stdout
        matched_version = self._version_pattern.match(output)
        if matched_version:
            major = matched_version.group("major")
            minor = matched_version.group("minor")
            patch = matched_version.group("patch")
            return VersionInfo(int(major), int(minor), int(patch))
        raise LisaException("fail to get gcc version")

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("gcc")
        return self._check_exists()

    def install_cpp_compiler(self) -> None:
        node_os = self.node.os
        if isinstance(node_os, Debian):
            node_os.install_packages("g++")
        elif (
            isinstance(node_os, Fedora)
            or isinstance(node_os, Suse)
            or isinstance(node_os, CBLMariner)
        ):
            node_os.install_packages("gcc-c++")
        else:
            raise UnsupportedDistroException(
                node_os,
                "No support for installing g++ for this distro in the Lisa[GCC] tool.",
            )
