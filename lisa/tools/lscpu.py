# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from enum import Enum
from typing import Any, List, Optional, Type

from assertpy import assert_that

from lisa.executable import Tool

CpuType = Enum(
    "CpuType",
    ["AMD", "Intel"],
)


class CPUInfo:
    def __init__(
        self,
        cpu: str,
        numa_node: str,
        socket: str,
        l1_data_cache: str,
        l1_instruction_cache: str,
        l2_cache: str,
        l3_cache: str,
    ) -> None:
        self.cpu = cpu
        self.numa_node = numa_node
        self.socket = socket
        self.l1_data_cache = l1_data_cache
        self.l1_instruction_cache = l1_instruction_cache
        self.l2_cache = l2_cache
        self.l3_cache = l3_cache

    def __str__(self) -> str:
        return (
            f"cpu : {self.cpu}, "
            f"numa_node : {self.numa_node}, "
            f"socket : {self.socket}, "
            f"l1_data_cache : , {self.l1_data_cache}, "
            f"l1_instruction_cache : {self.l1_instruction_cache}, "
            f"l2_cache : {self.l2_cache}, "
            f"l3_cache : {self.l3_cache}"
        )

    def __repr__(self) -> str:
        return self.__str__()


class Lscpu(Tool):
    # CPU(s):              16
    __vcpu = re.compile(r"^CPU\(s\):[ ]+([\d]+)\r?$", re.M)
    __thread_per_core = re.compile(r"^Thread\(s\) per core:[ ]+([\d]+)\r?$", re.M)
    __core_per_socket = re.compile(r"^Core\(s\) per socket:[ ]+([\d]+)\r?$", re.M)
    __sockets = re.compile(r"^Socket\(s\):[ ]+([\d]+)\r?$", re.M)
    # Architecture:        x86_64
    __architecture_pattern = re.compile(r"^Architecture:\s+(.*)?\r$", re.M)
    __valid_architecture_list = ["x86_64"]
    # 0 0 0 0:0:0:0
    # 96 0 10 1:1:1:0
    _core_numa_mappings = re.compile(
        r"\s*(?P<cpu>\d+)\s+(?P<numa_node>\d+)\s+(?P<socket>\d+)\s+"
        r"(?P<l1_data_cache>\d+):(?P<l1_instruction_cache>\d+):"
        r"(?P<l2_cache>\d+):(?P<l3_cache>\d+)$"
    )

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
        matched = self.__vcpu.findall(result.stdout)
        assert_that(
            len(matched),
            f"cpu count should have exact one line, but got {matched}",
        ).is_equal_to(1)
        self._core_count = int(matched[0]) * 1

        return self._core_count

    def get_thread_per_core_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__thread_per_core.findall(result.stdout)
        assert_that(
            len(matched),
            f"thread per core count should have exact one line, but got {matched}",
        ).is_equal_to(1)

        return int(matched[0]) * 1

    def get_core_per_socket_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__core_per_socket.findall(result.stdout)
        assert_that(
            len(matched),
            f"core per socket count should have exact one line, but got {matched}",
        ).is_equal_to(1)

        return int(matched[0]) * 1

    def get_socket_count(self, force_run: bool = False) -> int:
        result = self.run(force_run=force_run)
        matched = self.__sockets.findall(result.stdout)
        assert_that(
            len(matched),
            f"socket count should have exact one line, but got {matched}",
        ).is_equal_to(1)

        return int(matched[0]) * 1

    def get_cpu_type(self, force_run: bool = False) -> CpuType:
        result = self.run(force_run=force_run)
        if "AuthenticAMD" in result.stdout:
            return CpuType.AMD
        elif "GenuineIntel" in result.stdout:
            return CpuType.Intel
        return CpuType.Intel

    def get_cpu_info(self) -> List[CPUInfo]:
        # `lscpu --extended=cpu,node,socket,cache` command return the
        # cpu info in the format :
        # CPU NODE SOCKET L1d:L1i:L2:L3
        # 0    0        0 0:0:0:0
        # 1    0        0 0:0:0:0
        result = self.run("--extended=cpu,node,socket,cache").stdout
        mappings_with_header = result.splitlines(keepends=False)
        mappings = mappings_with_header[1:]
        assert len(mappings) > 0
        output: List[CPUInfo] = []
        for item in mappings:
            match_result = self._core_numa_mappings.fullmatch(item)
            assert match_result
            output.append(
                CPUInfo(
                    cpu=match_result.group("cpu"),
                    numa_node=match_result.group("numa_node"),
                    socket=match_result.group("socket"),
                    l1_data_cache=match_result.group("l1_data_cache"),
                    l1_instruction_cache=match_result.group("l1_instruction_cache"),
                    l2_cache=match_result.group("l2_cache"),
                    l3_cache=match_result.group("l3_cache"),
                )
            )
        return output


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
