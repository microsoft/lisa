# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from .disks import DiskEphemeral, DiskPremiumLRS, DiskStandardLRS, DiskType
from .gpu import Gpu
from .nvme import Nvme
from .serial_console import SerialConsole
from .sriov import Sriov
from .startstop import StartStop

__all__ = [
    "DiskEphemeral",
    "DiskPremiumLRS",
    "DiskStandardLRS",
    "DiskType",
    "Gpu",
    "Nvme",
    "SerialConsole",
    "Sriov",
    "StartStop",
]
