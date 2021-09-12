# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from .disks import (
    Disk,
    DiskEphemeral,
    DiskPremiumSSDLRS,
    DiskStandardHDDLRS,
    DiskStandardSSDLRS,
)
from .gpu import Gpu
from .network_interface import NetworkInterface, Sriov, Synthetic
from .nvme import Nvme, NvmeSettings
from .serial_console import SerialConsole
from .startstop import StartStop

__all__ = [
    "Disk",
    "DiskEphemeral",
    "DiskPremiumSSDLRS",
    "DiskStandardHDDLRS",
    "DiskStandardSSDLRS",
    "Gpu",
    "Nvme",
    "NvmeSettings",
    "SerialConsole",
    "NetworkInterface",
    "Sriov",
    "Synthetic",
    "StartStop",
]
