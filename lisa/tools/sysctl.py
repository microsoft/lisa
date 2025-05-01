# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from lisa.executable import Tool
from lisa.operating_system import BSD


class Sysctl(Tool):
    _bsd_poll_enable = "polling"
    _bsd_poll_disable = "-polling"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._polling_enabled: bool = False
        self._original_values: Dict[str, str] = dict()

    @property
    def command(self) -> str:
        return "sysctl"

    @property
    def can_install(self) -> bool:
        return False

    def write(self, variable: str, value: str) -> None:
        try:
            _ = self._original_values[variable]
        except KeyError:
            self._original_values[variable] = self.get(variable, force_run=True)
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
        if self._polling_enabled:
            return
        self._polling_enabled = True
        if isinstance(self.node.os, BSD):
            self.node.execute(
                "for i in `ifconfig -l` ; do "
                f"ifconfig $i {self._bsd_poll_enable}; done",
                sudo=True,
                shell=True,
            )
        else:
            for key in ["net.core.busy_poll", "net.core.busy_read"]:
                self._original_values[key] = self.get(key, force_run=True)
                self.write(key, value)

    def reset(self) -> None:
        # NOTE: handle BSD idiosyncracy w busy polling
        # see: https://man.freebsd.org/cgi/man.cgi?query=polling
        # The historic kern.polling.enable, which enabled polling for all inter-
        #  faces, can be replaced with the following code:
        #  for i in `ifconfig	-l` ;
        #    do ifconfig $i polling; # use -polling to disable
        #  done
        if self._polling_enabled and isinstance(self.node.os, BSD):
            self.node.execute(
                "for i in `ifconfig -l` ; do "
                f"ifconfig $i {self._bsd_poll_disable}; done",
                sudo=True,
                shell=True,
            )
        # clear any leftover variables
        keys = [x for x in self._original_values]
        for key in keys:
            original_value = self._original_values.pop(key)
            self.write(key, original_value)
        self._polling_enabled = False
