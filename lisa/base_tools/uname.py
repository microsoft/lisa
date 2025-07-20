# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from semver import VersionInfo

from lisa.executable import Tool
from lisa.util import LisaException, parse_version

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.operating_system import CpuArchitecture


@dataclass
class UnameResult:
    has_result: bool
    kernel_version: VersionInfo
    kernel_version_raw: str = ""
    hardware_platform: str = ""
    operating_system: str = ""
    uname_version: str = ""

    def __repr__(self) -> str:
        return (
            f"kernel version: {self.kernel_version_raw}, "
            f"hardware platform: {self.hardware_platform}, "
            f"operating system: {self.operating_system}, "
            f"uname version: {self.uname_version}, "
        )


class Uname(Tool):
    # 5.4.0-1056-azure #58~18.04.1-Ubuntu SMP Wed Jul 28 23:14:18 UTC 2021
    #   x86_64 GNU/Linux
    _key_info_pattern = re.compile(
        r"(?P<kernel_version>[^ ]*?) (?P<uname_version>[\w\W]*) (?P<platform>[\w\W]+?) "
        r"(?P<os>[\w\W]+?)$"
    )

    # x86_64
    # aarch64
    # Pattern for uname -m output (single line with architecture)
    _architecture_pattern = re.compile(r"^(\w+)$")

    @classmethod
    def create(cls, node: "Node", *args: Any, **kwargs: Any) -> Tool:
        # This file is a base tool, which is used by os. To avoid circular
        # import, the class name string is used here.
        if "FreeBSD" in node.os.name:
            return FreeBSDUname(node)
        else:
            return Uname(node)

    @property
    def command(self) -> str:
        return "uname"

    def _check_exists(self) -> bool:
        return True

    def get_linux_information(
        self, force_run: bool = False, no_error_log: bool = False
    ) -> UnameResult:
        self.initialize()
        cmd_result = self.run(
            "-vrmo", force_run=force_run, no_error_log=no_error_log, no_info_log=True
        )
        if cmd_result.exit_code != 0:
            result = UnameResult(False, VersionInfo(0))
        else:
            match_result = self._key_info_pattern.fullmatch(cmd_result.stdout)
            if not match_result:
                raise LisaException(f"no result matched, stdout: '{cmd_result.stdout}'")
            result = UnameResult(
                has_result=True,
                kernel_version=parse_version(match_result.group("kernel_version")),
                kernel_version_raw=match_result.group("kernel_version"),
                uname_version=match_result.group("uname_version"),
                hardware_platform=match_result.group("platform"),
                operating_system=match_result.group("os"),
            )

        return result

    def get_machine_architecture(self, force_run: bool = False) -> "CpuArchitecture":
        # To avoid circular import
        from lisa.operating_system import CpuArchitecture

        arch_map = {
            "x86_64": CpuArchitecture.X64,
            "amd64": CpuArchitecture.X64,
            "aarch64": CpuArchitecture.ARM64,
            "arm64": CpuArchitecture.ARM64,
            "i386": CpuArchitecture.I386,
        }
        self.initialize()
        result = self.run("-m", force_run=force_run)
        if result.exit_code != 0:
            raise LisaException(
                f"failed to get machine architecture, {result.stderr} {result.stdout}"
            )
        matched = self._architecture_pattern.findall(result.stdout.strip())
        if not matched:
            raise LisaException("The output of 'uname -m' is not expected.")
        arch_str = matched[0].lower()
        return arch_map.get(arch_str, CpuArchitecture.UNKNOWN)


class FreeBSDUname(Uname):
    # FreeBSD 14.1-RELEASE-p7 FreeBSD 14.1-RELEASE-p7 GENERIC arm64
    _key_info_pattern = re.compile(
        r"^(?P<os>[^ ]*?) (?P<kernel_version>[\w\W]*?) [^ ]*? [\w\W]*? "
        r"(?P<uname_version>[\w\W]+?) (?P<platform>[\w\W]+?)$"
    )
