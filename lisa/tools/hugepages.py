# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from enum import Enum
from typing import Any, Set

from assertpy import assert_that

from lisa.executable import Tool
from lisa.tools.echo import Echo
from lisa.tools.free import Free
from lisa.tools.ls import Ls
from lisa.tools.lscpu import Lscpu
from lisa.tools.mkfs import FileSystem
from lisa.tools.mount import Mount
from lisa.util import NotEnoughMemoryException, UnsupportedOperationException

PATTERN_HUGEPAGE = re.compile(
    r"^.*hugepages-(?P<hugepage_size_in_kb>\d+)kB.*",
)


class HugePageSize(Enum):
    HUGE_1GB = 1048576
    HUGE_2MB = 2048
    HUGE_512MB = 524288
    HUGE_16GB = 16777216


class Hugepages(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._hugepages_dir_path = "/sys/devices/system/node/node*/hugepages"

    def get_hugepage_sizes_in_kb(self) -> Set[int]:
        """
        This function get the hugepage sizes in kB available on the system.
        This is done by listing the hugepages directory
        and extracting the size from the directory name.
        e.g. [
        "'/sys/devices/system/node/node0/hugepages/hugepages-16777216kB/'",
        "'/sys/devices/system/node/node0/hugepages/hugepages-2048kB/'",
        "'/sys/devices/system/node/node0/hugepages/hugepages-524288kB/'"
        ]
        """
        hugepage_sizes: Set[int] = set()
        ls = self.node.tools[Ls]
        # if not ls.path_exists(self._hugepages_dir_path, sudo=True):
        #     raise SkippedException(f"path: {self._hugepages_dir_path} does not exist")
        hugepage_size_dir_names = ls.list_dir(self._hugepages_dir_path, sudo=True)
        for hugepage_size_dir_name in hugepage_size_dir_names:
            matched_hugepage = PATTERN_HUGEPAGE.match(hugepage_size_dir_name)
            if not matched_hugepage:
                raise UnsupportedOperationException(
                    "No supported hugepage size found in the"
                    f"list: {hugepage_size_dir_name}"
                )
            hugepage_sizes.add(int(matched_hugepage.group("hugepage_size_in_kb")))
        return hugepage_sizes

    def _enable_hugepages(
        self, hugepage_size_kb: HugePageSize, request_space_kb: int
    ) -> None:
        echo = self.node.tools[Echo]
        meminfo = self.node.tools[Free]
        numa_nodes = self.node.tools[Lscpu].get_numa_node_count()
        # ask for enough space, note that we enable pages per numa node

        free_memory_kb = meminfo.get_free_memory_kb()

        if free_memory_kb < request_space_kb:
            raise NotEnoughMemoryException(
                f"Not enough {hugepage_size_kb.value} KB pages "
                "available for DPDK! "
                f"Requesting {request_space_kb} KB found {free_memory_kb} "
                "KB free."
            )
        total_request_pages = request_space_kb // hugepage_size_kb.value
        pages_per_numa_node = total_request_pages // numa_nodes
        assert_that(pages_per_numa_node).described_as(
            "Must request huge page count > 0. Verify this system has enough "
            "free memory to allocate ~2GB of hugepages"
        ).is_greater_than(0)
        for i in range(numa_nodes):
            # nr_hugepages will be written with the number calculated
            # based on 2MB hugepages if not specified, subject to change
            # this based on further discussion
            echo.write_to_file(
                f"{pages_per_numa_node}",
                self.node.get_pure_path(
                    f"/sys/devices/system/node/node{i}/hugepages/"
                    f"hugepages-{hugepage_size_kb.value}kB/nr_hugepages"
                ),
                sudo=True,
            )

    def init_hugepages(self, hugepage_size: HugePageSize, minimum_gb: int = 2) -> None:
        mount = self.node.tools[Mount]
        hugepage_sizes = self.get_hugepage_sizes_in_kb()
        minimum_kb = minimum_gb * 1024 * 1024
        if hugepage_size.value not in hugepage_sizes:
            raise UnsupportedOperationException(
                f"Supported hugepage sizes in kB are: {hugepage_sizes}."
                f" {hugepage_size.value} kB size is not available"
            )
        if not mount.check_mount_point_exist(f"/mnt/huge-{hugepage_size.value}kb"):
            mount.mount(
                name="nodev",
                point=f"/mnt/huge-{hugepage_size.value}kb",
                fs_type=FileSystem.hugetlbfs,
                options=f"pagesize={hugepage_size.value}KB",
            )
        self._enable_hugepages(
            hugepage_size_kb=hugepage_size, request_space_kb=minimum_kb
        )
