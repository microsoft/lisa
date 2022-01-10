from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from lisa.util import constants


@dataclass
class MessageBase:
    type: str = "Base"
    elapsed: float = 0


TestRunStatus = Enum(
    "TestRunStatus",
    [
        "INITIALIZING",
        "RUNNING",
        "SUCCESS",
        "FAILED",
    ],
)


@dataclass
class TestRunMessage(MessageBase):
    type: str = "TestRun"
    status: TestRunStatus = TestRunStatus.INITIALIZING
    test_project: str = ""
    test_pass: str = ""
    tags: Optional[List[str]] = None
    run_name: str = ""
    message: str = ""


@dataclass
class PerfMessage(MessageBase):
    type: str = "Performance"


DiskSetupType = Enum(
    "DiskSetupType",
    [
        "raw",
        "raid0",
    ],
)


DiskType = Enum(
    "DiskType",
    [
        "nvme",
        "premiumssd",
    ],
)


@dataclass
class DiskPerformanceMessage(PerfMessage):
    tool: str = constants.DISK_PERFORMANCE_TOOL
    test_case_name: str = ""
    platform: str = ""
    location: str = ""
    host_version: str = ""
    guest_os_type: str = "Linux"
    distro_version: str = ""
    vmsize: str = ""
    kernel_version: str = ""
    lis_version: str = ""
    disk_setup_type: DiskSetupType = DiskSetupType.raw
    block_size: int = 0
    disk_type: DiskType = DiskType.nvme
    core_count: int = 0
    disk_count: int = 0
    qdepth: int = 0
    iodepth: int = 0
    numjob: int = 0
    test_date: datetime = datetime.utcnow()
    read_iops: Decimal = Decimal(0)
    read_lat_usec: Decimal = Decimal(0)
    randread_iops: Decimal = Decimal(0)
    randread_lat_usec: Decimal = Decimal(0)
    write_iops: Decimal = Decimal(0)
    write_lat_usec: Decimal = Decimal(0)
    randwrite_iops: Decimal = Decimal(0)
    randwrite_lat_usec: Decimal = Decimal(0)


@dataclass
class NetworkLatencyPerformanceMessage(PerfMessage):
    test_case_name: str = ""
    platform: str = ""
    location: str = ""
    host_version: str = ""
    guest_os_type: str = "Linux"
    distro_version: str = ""
    vmsize: str = ""
    kernel_version: str = ""
    lis_version: str = ""
    ip_version: str = "IPv4"
    protocol_type: str = "TCP"
    data_path: str = ""
    test_date: datetime = datetime.utcnow()
    max_latency_us: Decimal = Decimal(0)
    average_latency_us: Decimal = Decimal(0)
    min_latency_us: Decimal = Decimal(0)
    latency95_percentile_us: Decimal = Decimal(0)
    latency99_percentile_us: Decimal = Decimal(0)
    interval_us: int = 0
    frequency: int = 0


@dataclass
class NetworkPPSPerformanceMessage(PerfMessage):
    test_execution_tag: str = ""
    platform: str = ""
    location: str = ""
    host_version: str = ""
    guest_os_type: str = "Linux"
    distro_version: str = ""
    vmsize: str = ""
    kernel_version: str = ""
    ip_version: str = "IPv4"
    protocol_type: str = "TCP"
    data_path: str = ""
    test_type: str = ""
    test_date: datetime = datetime.utcnow()
    rx_pps_minimum: Decimal = Decimal(0)
    rx_pps_average: Decimal = Decimal(0)
    rx_pps_maximum: Decimal = Decimal(0)
    tx_pps_minimum: Decimal = Decimal(0)
    tx_pps_average: Decimal = Decimal(0)
    tx_pps_maximum: Decimal = Decimal(0)
    rx_tx_pps_minimum: Decimal = Decimal(0)
    rx_tx_pps_average: Decimal = Decimal(0)
    rx_tx_pps_maximum: Decimal = Decimal(0)
