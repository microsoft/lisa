# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from .acc import ACC
from .disks import (
    Disk,
    DiskEphemeral,
    DiskPremiumSSDLRS,
    DiskStandardHDDLRS,
    DiskStandardSSDLRS,
)
from .gpu import Gpu, GpuEnabled, GpuSettings
from .hibernation import Hibernation, HibernationEnabled, HibernationSettings
from .infiniband import Infiniband
from .network_interface import NetworkInterface, Sriov, Synthetic
from .nvme import Nvme, NvmeSettings
from .resize import Resize
from .security_profile import (
    SecureBootEnabled,
    SecurityProfile,
    SecurityProfileSettings,
)
from .serial_console import SerialConsole
from .startstop import StartStop, StopState

__all__ = [
    "ACC",
    "Disk",
    "DiskEphemeral",
    "DiskPremiumSSDLRS",
    "DiskStandardHDDLRS",
    "DiskStandardSSDLRS",
    "Gpu",
    "GpuEnabled",
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
    "SecureBootEnabled",
    "SecurityProfile",
    "SecurityProfileSettings",
    "Sriov",
    "StopState",
    "Synthetic",
    "StartStop",
]
