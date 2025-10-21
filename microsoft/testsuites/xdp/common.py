# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from time import sleep
from typing import Dict, List, Pattern

from lisa import Logger, Node, SkippedException, UnsupportedDistroException
from lisa.nic import NicInfo
from lisa.tools import Echo, Ethtool, Ls, Mount
from lisa.tools.mkfs import FileSystem
from microsoft.testsuites.xdp.xdpdump import XdpDump

_rx_drop_patterns = [
    # rx_queue_0_xdp_drop
    re.compile(r"^rx_queue_\d+_xdp_drop$"),
    # rx_xdp_drop
    re.compile(r"^rx_xdp_drop$"),
    # rx_0_xdp_drop
    re.compile(r"^rx_\d+_xdp_drop$"),
]
_tx_forwarded_patterns = [
    # rx_xdp_tx
    re.compile(r"^rx_xdp_tx$"),
    # rx_xdp_0_tx
    re.compile(r"^rx_xdp_\d+_tx$"),
    # rx_xdp_tx_xmit
    re.compile(r"^rx_xdp_tx_xmit$"),
]
# /sys/devices/system/node/node0/hugepages/hugepages-1048576kB
# /sys/devices/system/node/node0/hugepages/hugepages-32768kB
# /sys/devices/system/node/node0/hugepages/hugepages-2048kB
# /sys/devices/system/node/node0/hugepages/hugepages-64kB
_huge_page_size_pattern = re.compile(r"hugepages-(?P<size>\d+)kB", re.I)
_nic_not_found = re.compile(r"Couldn't get device .* statistics", re.M)


def get_xdpdump(node: Node) -> XdpDump:
    try:
        xdpdump = node.tools[XdpDump]
    except UnsupportedDistroException as e:
        raise SkippedException(e)

    return xdpdump


def get_forwarded_count(
    node: Node, nic: NicInfo, previous_count: int, log: Logger
) -> int:
    return _aggregate_count(
        node=node,
        nic=nic,
        previous_count=previous_count,
        log=log,
        counter_name="xdp forwarded",
        patterns=_tx_forwarded_patterns,
    )


def get_dropped_count(
    node: Node, nic: NicInfo, previous_count: int, log: Logger
) -> int:
    return _aggregate_count(
        node=node,
        nic=nic,
        previous_count=previous_count,
        log=log,
        counter_name="xdp dropped",
        patterns=_rx_drop_patterns,
    )


def set_hugepage(node: Node) -> None:
    mount = node.tools[Mount]
    for point, options in _get_mount_options(node).items():
        mount.mount(
            name="nodev", point=point, fs_type=FileSystem.hugetlbfs, options=options
        )
    echo = node.tools[Echo]
    echo.write_to_file(
        "4096",
        node.get_pure_path(
            "/sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
        ),
        sudo=True,
    )
    echo.write_to_file(
        "1",
        node.get_pure_path(
            "/sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
        ),
        sudo=True,
        ignore_error=True,
    )
    echo.write_to_file(
        "1",
        node.get_pure_path(
            "/sys/devices/system/node/node0/hugepages/hugepages-16777216kB/nr_hugepages"
        ),
        sudo=True,
        ignore_error=True,
    )


def remove_hugepage(node: Node) -> None:
    huge_page_disks = _get_mount_options(node)
    echo = node.tools[Echo]
    echo.write_to_file(
        "0",
        node.get_pure_path(
            "/sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
        ),
        sudo=True,
    )
    echo.write_to_file(
        "0",
        node.get_pure_path(
            "/sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
        ),
        sudo=True,
        ignore_error=True,
    )
    echo.write_to_file(
        "0",
        node.get_pure_path(
            "/sys/devices/system/node/node0/hugepages/hugepages-16777216kB/nr_hugepages"
        ),
        sudo=True,
        ignore_error=True,
    )

    mount = node.tools[Mount]
    for point in huge_page_disks:
        mount.umount(disk_name="nodev", point=point, fs_type="hugetlbfs", erase=False)
        pure_path = node.get_pure_path(point)
        node.execute(f"rm -rf {pure_path}", sudo=True)


def _aggregate_count(
    node: Node,
    nic: NicInfo,
    previous_count: int,
    log: Logger,
    counter_name: str,
    patterns: List[Pattern[str]],
) -> int:
    ethtool = node.tools[Ethtool]
    nic_names = [nic.name, nic.lower]

    # aggregate xdp drop count by different nic type
    new_count = -previous_count
    for nic_name in nic_names:
        # there may not have vf nic
        if not nic_name:
            continue
        attempts = 0
        max_attempts = 4
        while attempts < max_attempts:
            try:
                stats = ethtool.get_device_statistics(
                    interface=nic_name, force_run=True
                ).counters
                break
            except Exception as e:
                if _nic_not_found.search(str(e)):
                    log.debug(f"nic {nic_name} not found, need to reload nics")
                    sleep(2)
                    node.nics.reload()
                    nic_name = node.nics.get_primary_nic().lower
                    attempts += 1
                else:
                    raise e
        # the name and pattern ordered by syn/vf
        for pattern in patterns:
            items = {key: value for key, value in stats.items() if pattern.match(key)}
            if items:
                log.debug(f"found {counter_name} stats: {items}")
                new_count += sum(value for value in items.values())

    log.debug(f"{counter_name} count: {new_count}")
    return new_count


def _get_mount_options(node: Node) -> Dict[str, str]:
    folders = node.tools[Ls].list_dir("/sys/devices/system/node/node0/hugepages")
    matches = [
        match.group("size")
        for match in re.finditer(_huge_page_size_pattern, "".join(folders))
    ]
    max_value_kb = max(list(map(int, matches)))
    if max_value_kb >= 1024 * 1024:
        max_value_gb = int(max_value_kb / (1024 * 1024))
        huge_page_disks = {
            "/mnt/huge": "",
            f"/mnt/huge{max_value_gb}g": f"pagesize={max_value_gb}G",
        }
    else:
        max_value_mb = int(max_value_kb / 1024)
        huge_page_disks = {
            "/mnt/huge": "",
            f"/mnt/huge{max_value_mb}m": f"pagesize={max_value_mb}M",
        }
    return huge_page_disks
