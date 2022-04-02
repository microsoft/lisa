# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from .disks import (
    Disk,
    DiskEphemeral,
    DiskPremiumSSDLRS,
    DiskStandardHDDLRS,
    DiskStandardSSDLRS,
)
from .gpu import Gpu, GpuSettings
from .hibernation import Hibernation, HibernationEnabled, HibernationSettings
from .infiniband import Infiniband
from .network_interface import NetworkInterface, Sriov, Synthetic
from .nvme import Nvme, NvmeSettings
from .resize import Resize
from .serial_console import SerialConsole
from .startstop import StartStop

__all__ = [
    "Disk",
    "DiskEphemeral",
    "DiskPremiumSSDLRS",
    "DiskStandardHDDLRS",
    "DiskStandardSSDLRS",
    "Gpu",
    "GpuSettings",
    "Hibernation",
    "HibernationEnabled",
    "HibernationSettings",
    "Infiniband",
    "Nvme",
    "NvmeSettings",
    "SerialConsole",
    "NetworkInterface",
    "Resize",
    "Sriov",
    "Synthetic",
    "StartStop",
]
