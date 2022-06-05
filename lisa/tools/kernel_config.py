# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePosixPath
from typing import Any

from lisa.executable import Tool
from lisa.tools import Uname


class KernelConfig(Tool):
    """
    KernelConfig is a tool that can check config exists or not, config is set as
    built-in or as module.
    """

    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def is_built_in(self, config_name: str) -> bool:
        return (
            self.node.execute(
                f"grep ^{config_name}=y {self.config_path}", sudo=True, shell=True
            ).exit_code
            == 0
        )

    def is_built_as_module(self, config_name: str) -> bool:
        return (
            self.node.execute(
                f"grep ^{config_name}=m {self.config_path}", sudo=True, shell=True
            ).exit_code
            == 0
        )

    def is_enabled(self, config_name: str) -> bool:
        return self.is_built_as_module(config_name) or self.is_built_in(config_name)

    def _check_exists(self) -> bool:
        return self.node.shell.exists(PurePosixPath(self.config_path))

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        uname_tool = self.node.tools[Uname]
        kernel_ver = uname_tool.get_linux_information().kernel_version
        self.config_path: str = f"/boot/config-{kernel_ver}"
