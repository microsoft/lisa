# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import TYPE_CHECKING, Any

from lisa.executable import Tool
from lisa.util import get_matched_str

if TYPE_CHECKING:
    from lisa.operating_system import Posix


class Modinfo(Tool):
    # (note - version_pattern is found only when LIS drivers are installed)
    # modinfo hv_vmbus
    # version:        3.1
    # negative case (SHOULD NOT BE MATCHED)
    # parm:           max_version:Maximal VMBus protocol version which can be
    #                  negotiated (uint)
    _version_pattern = re.compile(r"^version:[ \t]*([^ \r\n]*)", re.M)
    # filename:       /lib/modules/2.6.32-754.29.1.el6.x86_64/kernel/drivers/hv/
    #                 hv_vmbus.ko
    _filename_pattern = re.compile(r"^filename:[ \t]*([^ \r\n]*)", re.M)

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        # Check if modinfo command actually exists on the system
        result = self.node.execute("which modinfo", shell=True, no_error_log=True)
        return result.exit_code == 0

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "modinfo"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        # modinfo is part of kmod package on most distributions
        posix_os.install_packages("kmod")
        return self._check_exists()

    def get_info(
        self,
        mod_name: str,
        force_run: bool = False,
        ignore_error: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
    ) -> str:
        result = self.run(
            mod_name,
            sudo=True,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
            shell=True,
        )
        if not ignore_error:
            result.assert_exit_code(0, f"Modinfo failed for module {mod_name}")
        return result.stdout

    def get_version(
        self, mod_name: str, force_run: bool = False, ignore_error: bool = True
    ) -> str:
        output = self.get_info(
            mod_name=mod_name,
            force_run=force_run,
            ignore_error=ignore_error,
            no_info_log=True,
            no_error_log=True,
        )
        return get_matched_str(output, self._version_pattern)

    def get_filename(
        self,
        mod_name: str,
        force_run: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
    ) -> str:
        output = self.get_info(
            mod_name=mod_name,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
        )
        found_filename = get_matched_str(output, self._filename_pattern)
        return found_filename if found_filename else ""
