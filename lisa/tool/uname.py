import re
from typing import Tuple

from lisa.core.tool import Tool
from lisa.util.exceptions import LisaException


class Uname(Tool):
    def initialize(self) -> None:
        self.key_info_pattern = re.compile(
            r"(?P<release>[^ ]*?) (?P<version>[\w\W]*) (?P<platform>[\w\W]+?) "
            r"(?P<os>[\w\W]+?)$"
        )
        # uname's result suppose not be changed frequently,
        #  so cache it for performance.
        self.has_result: bool = False
        self.is_linux: bool = True
        self.kernel_release: str = ""
        self.kernel_version: str = ""
        self.hardware_platform: str = ""
        self.operating_system: str = ""

    @property
    def command(self) -> str:
        return "uname"

    @property
    def _is_installed_internal(self) -> bool:
        return True

    def get_linux_information(
        self, force: bool = False, no_error_log: bool = False
    ) -> Tuple[str, str, str, str]:
        """
            return:
                kernel-release
                kernel-version
                hardware-platform
                operating-system
        """

        if (not self.has_result) or force:
            cmd_result = self.run("-vrio", no_error_log=no_error_log)

            if cmd_result.exit_code != 0:
                self.is_linux = False
            else:
                match_result = self.key_info_pattern.fullmatch(cmd_result.stdout)
                if not match_result:
                    raise LisaException(
                        f"no result matched, stdout: '{cmd_result.stdout}'"
                    )
                self.kernel_release = match_result.group("release")
                self.kernel_version = match_result.group("version")
                self.hardware_platform = match_result.group("platform")
                self.operating_system = match_result.group("os")
            self.has_result = True

        return (
            self.kernel_release,
            self.kernel_version,
            self.hardware_platform,
            self.operating_system,
        )
