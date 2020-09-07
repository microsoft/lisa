import re
from dataclasses import dataclass

from lisa.executable import Tool
from lisa.util import LisaException


@dataclass
class UnameResult:
    has_result: bool
    kernel_release: str = ""
    kernel_version: str = ""
    hardware_platform: str = ""
    operating_system: str = ""


class Uname(Tool):
    _key_info_pattern = re.compile(
        r"(?P<release>[^ ]*?) (?P<version>[\w\W]*) (?P<platform>[\w\W]+?) "
        r"(?P<os>[\w\W]+?)$"
    )

    def initialize(self) -> None:
        # uname's result suppose not be changed frequently,
        #  so cache it for performance.
        self.has_result: bool = False
        self.is_linux: bool = True

    @property
    def command(self) -> str:
        return "uname"

    @property
    def _is_installed_internal(self) -> bool:
        return True

    def get_linux_information(
        self, force: bool = False, no_error_log: bool = False
    ) -> UnameResult:
        self.initialize()
        if (not self.has_result) or force:
            cmd_result = self.run("-vrio", no_error_log=no_error_log, no_info_log=True)

            if cmd_result.exit_code != 0:
                self.result = UnameResult(False, "", "", "", "")
                self._is_linux = False
            else:
                match_result = self._key_info_pattern.fullmatch(cmd_result.stdout)
                if not match_result:
                    raise LisaException(
                        f"no result matched, stdout: '{cmd_result.stdout}'"
                    )
                self.result = UnameResult(
                    has_result=True,
                    kernel_release=match_result.group("release"),
                    kernel_version=match_result.group("version"),
                    hardware_platform=match_result.group("platform"),
                    operating_system=match_result.group("os"),
                )
            self.has_result = True

        return self.result
