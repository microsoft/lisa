# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re

from lisa.executable import Tool
from lisa.util import LisaException, find_group_in_lines

# example output
#               total        used        free      shared  buff/cache   available
# Mem:        16310304      441732    15438492        2448      430080    15600880
# Swap:        4194304           0     4194304


class Free(Tool):
    # Mem:            9.0G        4.5G        412M         74M        4.1G        4.2G
    _mem_pattern = re.compile(
        r"^Mem: +(?P<total>\d+\.?\d*\w) +(?P<used>\d+\.?\d*\w) +(?P<free>\d+\.?\d*\w) +(?P<shared>\d+\.?\d*\w) +(?P<buff>\d+\.?\d*\w) +(?P<available>\d+\.?\d*\w)$"  # noqa: E501
    )

    @property
    def command(self) -> str:
        return "free"

    #     Usage:
    #  free [options]

    # Options:
    #  -b, --bytes         show output in bytes
    #      --kilo          show output in kilobytes
    #      --mega          show output in megabytes
    #      --giga          show output in gigabytes
    #      --tera          show output in terabytes
    #      --peta          show output in petabytes
    #  -k, --kibi          show output in kibibytes
    #  -m, --mebi          show output in mebibytes
    #  -g, --gibi          show output in gibibytes
    #      --tebi          show output in tebibytes
    #      --pebi          show output in pebibytes
    #  -h, --human         show human-readable output
    #      --si            use powers of 1000 not 1024
    #  -l, --lohi          show detailed low and high memory statistics
    #  -t, --total         show total for RAM + swap
    #  -s N, --seconds N   repeat printing every N seconds
    #  -c N, --count N     repeat printing N times, then exit
    #  -w, --wide          wide output

    # Starter data sizes, use Kibi/Mebi/Gibi

    def _get_header_index(self, header_name: str, header_line: str) -> int:
        # get index of header based on first line, add one to account
        # for first label field in the rest of the lines
        return 1 + header_line.split().index(header_name)

    def _get_field_bytes_kib(self, field_name: str, header_name: str) -> int:
        # Example output:
        #         total used free
        # Swap:   0     0    0

        # get the data
        out = self.run("-k", force_run=True).stdout
        lines = out.splitlines()

        # get offset for data when we split the line
        header_index = self._get_header_index(header_name, lines[0])

        for line in out.splitlines():
            if line.startswith(f"{field_name}:"):
                return int(line.split()[header_index])

        raise LisaException(f"Failed to get info for field {field_name}")

    def get_swap_size(self) -> int:
        # Return total swap size in Mebibytes
        return self._get_field_bytes_kib("Swap", "total") >> 10

    def get_free_memory_kb(self) -> int:
        return self._get_field_bytes_kib("Mem", "free")

    def get_free_memory_mb(self) -> int:
        return self._get_field_bytes_kib("Mem", "free") >> 10

    def get_free_memory_gb(self) -> int:
        return self._get_field_bytes_kib("Mem", "free") >> 20

    def get_total_memory_gb(self) -> int:
        return self._get_field_bytes_kib("Mem", "total") >> 20

    def get_total_memory(self) -> str:
        """
        Returns total memory in power of 1000 with unit
        Example: 20G
        """
        # Example
        #             total        used        free      shared  buff/cache   available
        # Mem:         9.0G        4.6G        751M         74M        3.7G        4.0G
        # Swap:         0B          0B          0B
        output = self.run("-h --si", shell=True).stdout

        group = find_group_in_lines(output, self._mem_pattern)
        total_memory = group["total"]
        return total_memory

    def log_memory_stats_mb(self) -> None:
        self.run("-m", shell=True, force_run=True, no_info_log=False)
