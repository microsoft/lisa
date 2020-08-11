import re
from typing import Tuple

from lisa.core.tool import Tool


class Uname(Tool):
    def initialize(self) -> None:
        self.key_info_pattern = re.compile(
            r"(?P<release>[^ ]*?) (?P<version>[\w\W]*) (?P<platform>[\w\W]+?) "
            r"(?P<os>[\w\W]+?)$"
        )
        # uname's result suppose not be changed frequently,
        #  so cache it for performance.
        self.hasResult: bool = False
        self.isLinux: bool = True
        self.kernelRelease: str = ""
        self.kernelVersion: str = ""
        self.hardwarePlatform: str = ""
        self.os: str = ""

    @property
    def command(self) -> str:
        return "uname"

    @property
    def canInstall(self) -> bool:
        return False

    @property
    def isInstalledInternal(self) -> bool:
        return True

    def getLinuxInformation(
        self, force: bool = False, noErrorLog: bool = False
    ) -> Tuple[str, str, str, str]:
        """
            return:
                kernel-release
                kernel-version
                hardware-platform
                os
        """

        if (not self.hasResult) or force:
            cmd_result = self.run("-vrio", noErrorLog=noErrorLog)

            if cmd_result.exitCode != 0:
                self.isLinux = False
            else:
                match_result = self.key_info_pattern.fullmatch(cmd_result.stdout)
                if not match_result:
                    raise Exception(f"no result matched, stdout: '{cmd_result.stdout}'")
                self.kernelRelease = match_result.group("release")
                self.kernelVersion = match_result.group("version")
                self.hardwarePlatform = match_result.group("platform")
                self.os = match_result.group("os")
            self.hasResult = True
        return (
            self.kernelRelease,
            self.kernelVersion,
            self.hardwarePlatform,
            self.os,
        )
