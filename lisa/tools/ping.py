# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Optional

from lisa.executable import Tool
from lisa.util.process import Process

INTERNET_PING_ADDRESS = "8.8.8.8"


class Ping(Tool):
    @property
    def command(self) -> str:
        return "ping"

    def ping_async(
        self,
        target: str = "",
        nic_name: str = "",
        count: int = 5,
        interval: float = 0.2,
        package_size: Optional[int] = None,
    ) -> Process:
        if not target:
            target = INTERNET_PING_ADDRESS
        args: str = f"{target} -c {count} -i {interval} -O"
        if nic_name:
            args += f" -I {nic_name}"
        if package_size:
            args += f" -s {package_size}"

        return self.run_async(args, force_run=True)

    def ping(
        self,
        target: str = "",
        nic_name: str = "",
        count: int = 5,
        interval: float = 0.2,
        package_size: Optional[int] = None,
        ignore_error: bool = False,
    ) -> bool:
        if not target:
            target = INTERNET_PING_ADDRESS
        result = self.ping_async(
            target=target,
            nic_name=nic_name,
            count=count,
            interval=interval,
            package_size=package_size,
        ).wait_result()
        if not ignore_error:
            result.assert_exit_code(
                message="failed on ping. The server may not be reached.",
            )
        # return ping passed or not.
        return result.exit_code == 0
