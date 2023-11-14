# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from .acc import ACC
from .cvm_nested_virtualization import CVMNestedVirtualization
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
from .isolated_resource import IsolatedResource
from .nested_virtualization import NestedVirtualization
from .network_interface import NetworkInterface, Sriov, Synthetic
from .nfs import Nfs
from .nvme import Nvme, NvmeSettings
from .password_extension import PasswordExtension
from .resize import Resize, ResizeAction
from .security_profile import (
    SecureBootEnabled,
    SecurityProfile,
    SecurityProfileSettings,
    SecurityProfileType,
)
from .serial_console import SerialConsole
from .startstop import StartStop, StopState

__all__ = [
    "ACC",
    "CVMNestedVirtualization",
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
    "IsolatedResource",
    "NestedVirtualization",
    "Nfs",
    "Nvme",
    "NvmeSettings",
    "SerialConsole",
    "NetworkInterface",
    "PasswordExtension",
    "Resize",
    "ResizeAction",
    "SecureBootEnabled",
    "SecurityProfile",
    "SecurityProfileSettings",
    "SecurityProfileType",
    "Sriov",
    "StopState",
    "Synthetic",
    "StartStop",
]
