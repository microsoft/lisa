# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.util.process import Process

_default_internet_address = "bing.com"


class Ping(Tool):
    @property
    def command(self) -> str:
        return "ping"

    def ping_async(
        self,
        target: str = _default_internet_address,
        nic_name: str = "",
        count: int = 5,
        interval: float = 0.2,
    ) -> Process:
        args: str = f"{target} -c {count} -i {interval}"
        if nic_name:
            args += f" -I {nic_name}"
        return self.run_async(args, force_run=True)

    def ping(
        self,
        target: str = _default_internet_address,
        nic_name: str = "",
        count: int = 5,
        interval: float = 0.2,
        ignore_error: bool = False,
    ) -> bool:
        result = self.ping_async(
            target=target, nic_name=nic_name, count=count, interval=interval
        ).wait_result()
        if not ignore_error:
            result.assert_exit_code(
                message="failed on ping. The server may not be reached.",
            )
        # return ping passed or not.
        return result.exit_code == 0
