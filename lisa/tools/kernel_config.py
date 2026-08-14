# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from enum import Enum
from typing import Any, Optional, Type

from assertpy.assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import CoreOs
from lisa.tools import Cat, Uname
from lisa.util import find_groups_in_lines


class ModulesType(Enum):
    BUILT_IN = "y"
    MODULE = "m"
    NOT_BUILT = "n"


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

    def _grep_config(self, pattern: str) -> bool:
        # /proc/config.gz is gzip-compressed and must be read with zcat, while
        # the /boot/config-* files are plain text and can be grepped directly.
        if self.config_path.endswith(".gz"):
            command = f"zcat {self.config_path} | grep {pattern}"
        else:
            command = f"grep {pattern} {self.config_path}"
        return self.node.execute(command, sudo=True, shell=True).exit_code == 0

    def is_kernel_config_set_to(
        self, config_name: str, config_value: ModulesType
    ) -> bool:
        return self._grep_config(f"^{config_name}={config_value.value}")

    def is_built_in(self, config_name: str) -> bool:
        return self._grep_config(f"^{config_name}=y")

    def is_built_as_module(self, config_name: str) -> bool:
        return self._grep_config(f"^{config_name}=m")

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
            boot_config_path = f"/usr/boot/config-{kernel_ver}"
        else:
            boot_config_path = f"/boot/config-{kernel_ver}"
        # Some kernels (e.g. locally built ones with a version suffix like
        # "6.6.0+") don't ship a matching /boot/config-<kernel_ver> file. Fall
        # back to /proc/config.gz, which is exposed when CONFIG_IKCONFIG_PROC is
        # enabled, so kernel config lookups still work.
        if self.node.execute(f"ls -lt {boot_config_path}", sudo=True).exit_code == 0:
            self.config_path = boot_config_path
        else:
            self.config_path = "/proc/config.gz"


class KernelConfigFreeBSD(KernelConfig):
    _MODULE_CONFIG_MAP = {
        "CONFIG_MLX5_CORE": "mlx5en_load",
        "CONFIG_MLX4_CORE": "mlx4en_load",
    }

    def is_built_in(self, config_name: str) -> bool:
        return self.node.tools[KLDStat].module_statically_linked(config_name)

    def is_built_as_module(self, config_name: str) -> bool:
        output = self.node.tools[Cat].read(self.config_path, sudo=True)
        if config_name in self._MODULE_CONFIG_MAP:
            config_name = self._MODULE_CONFIG_MAP[config_name]
        return f'{config_name}="YES"' in output

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.config_path = "/boot/loader.conf"


class KLDStat(Tool):
    _MODULE_DRIVER_MAPPING = {
        "mlx5_core": "mlx5en",
        "mlx4_core": "mlx4en",
    }

    # Id Refs Address                Size Name
    # 2    1 0xffffffff8213f000    23bc8 mlx4en.ko
    _LOADED_MODULES = re.compile(
        r"(?P<id>\d+)\s+(?P<refs>\d+)\s+(?P<address>0x[0-9a-f]+)\s+(?P<size>\S+)\s+(?P<name>\w+).ko"  # noqa: E501
    )

    @property
    def command(self) -> str:
        return "kldstat"

    def module_statically_linked(
        self,
        mod_name: str,
    ) -> bool:
        output = self.run("-v -i 1", sudo=True).stdout
        return mod_name in output

    def module_exists(
        self,
        name: str,
    ) -> bool:
        if name in self._MODULE_DRIVER_MAPPING:
            name = self._MODULE_DRIVER_MAPPING[name]

        output = self.run(
            f"-n {name}",
            sudo=True,
            force_run=True,
        ).stdout
        matched = find_groups_in_lines(output, self._LOADED_MODULES, False)
        if len(matched) > 0:
            assert_that(len(matched)).is_equal_to(1)
            return matched[0]["name"] == name and int(matched[0]["refs"]) > 0

        # Check if module is loaded in kernel
        output = self.node.execute(
            f"kldload {name}",
            sudo=True,
            shell=True,
        ).stdout

        if "module already loaded or in kernel" in output:
            return True

        return False
