# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.operating_system import BSD


class Sysctl(Tool):
    @property
    def command(self) -> str:
        return "sysctl"

    @property
    def can_install(self) -> bool:
        return False

    def write(self, variable: str, value: str) -> None:
        self.run(
            f"-w {variable}='{value}'",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"fail to set {variable} value to {value}"
            ),
        )

    def get(self, variable: str, force_run: bool = True) -> str:
        result = self.run(
            f"-n {variable}",
            force_run=force_run,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to get {variable}'s value",
        )
        return result.stdout

    def enable_busy_polling(self, value: str) -> None:
        # NOTE: handle BSD idiosyncracy
        # see: https://man.freebsd.org/cgi/man.cgi?query=polling
        # The historic kern.polling.enable, which enabled polling for all inter-
        #  faces, can be replaced with the following code:
        #  for i in `ifconfig	-l` ;
        #    do ifconfig $i polling; # use -polling to disable
        #  done
        bsd_poll_enable = "for i in `ifconfig -l` ; do ifconfig $i polling; done"
        if isinstance(self.node.os, BSD):
            self.node.execute(bsd_poll_enable, sudo=True, shell=True)
        else:
            self.write("net.core.busy_poll", value)
            self.write("net.core.busy_read", value)
