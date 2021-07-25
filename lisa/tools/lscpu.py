# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from enum import Enum
from typing import Any, Optional, Type

from assertpy import assert_that

from lisa.executable import Tool

CpuType = Enum(
    "CpuType",
    ["AMD", "Intel"],
)


class Lscpu(Tool):
    # CPU(s):              16
    __vcpu_sockets = re.compile(r"^CPU\(s\):[ ]+([\d]+)\r?$", re.M)
    # Architecture:        x86_64
    __architecture_pattern = re.compile(r"^Architecture:\s+(.*)?\r$", re.M)
    __valid_architecture_list = ["x86_64"]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._core_count: Optional[int] = None

    @property
    def command(self) -> str:
        return "lscpu"

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsLscpu

    def _check_exists(self) -> bool:
        return True

    def get_architecture(self, force_run: bool = False) -> str:
        architecture: str = ""
        result = self.run(force_run=force_run)
        matched = self.__architecture_pattern.findall(result.stdout)
        assert_that(
            matched,
            f"architecture should have exact one line, but got {matched}",
        ).is_length(1)
        architecture = matched[0]
        assert_that(
            [architecture],
            f"architecture {architecture} must be one of "
            f"{self.__valid_architecture_list}.",
        ).is_subset_of(self.__valid_architecture_list)
        return architecture

    def get_core_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__vcpu_sockets.findall(result.stdout)
        assert_that(
            len(matched),
            f"cpu count should have exact one line, but got {matched}",
        ).is_equal_to(1)
        self._core_count = int(matched[0]) * 1

        return self._core_count

    def get_cpu_type(self, force_run: bool = False) -> CpuType:
        result = self.run(force_run=force_run)
        if "AuthenticAMD" in result.stdout:
            return CpuType.AMD
        elif "GenuineIntel" in result.stdout:
            return CpuType.Intel
        return CpuType.Intel


class WindowsLscpu(Lscpu):
    @property
    def command(self) -> str:
        return "wmic cpu get"

    def get_core_count(self, force_run: bool = False) -> int:
        result = self.run("ThreadCount", force_run=force_run)
        lines = result.stdout.splitlines(keepends=False)
        assert "ThreadCount" == lines[0].strip(), f"actual: '{lines[0]}'"
        self._core_count = int(lines[2].strip())

        return self._core_count
