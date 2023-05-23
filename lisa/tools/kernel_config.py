# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, Optional, Type

from lisa.executable import Tool
from lisa.operating_system import CoreOs
from lisa.tools import Cat, Uname


class KernelConfig(Tool):
    """
    KernelConfig is a tool that can check config exists or not, config is set as
    built-in or as module.
    """

    @property
    def command(self) -> str:
        return ""

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return KernelConfigFreeBSD

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
        return (
            self.node.execute(f"ls -lt {self.config_path}", sudo=True)
        ).exit_code == 0

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.config_path: str = ""
        uname_tool = self.node.tools[Uname]
        kernel_ver = uname_tool.get_linux_information().kernel_version_raw
        if isinstance(self.node.os, CoreOs):
            self.config_path = f"/usr/boot/config-{kernel_ver}"
        else:
            self.config_path = f"/boot/config-{kernel_ver}"


class KernelConfigFreeBSD(KernelConfig):
    def is_built_in(self, config_name: str) -> bool:
        return self.node.tools[KLDStat].module_statically_linked(config_name)

    def is_built_as_module(self, config_name: str) -> bool:
        output = self.node.tools[Cat].read(self.config_path, sudo=True)
        return f'{config_name}="YES"' in output

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.config_path = "/boot/loader.conf"


class KLDStat(Tool):
    @property
    def command(self) -> str:
        return "kldstat"

    def module_statically_linked(
        self,
        mod_name: str,
    ) -> bool:
        output = self.run("-v -i 1", sudo=True).stdout
        return mod_name in output
