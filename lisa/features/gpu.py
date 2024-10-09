# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Any, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.base_tools import Wget
from lisa.base_tools.uname import Uname
from lisa.feature import Feature
from lisa.operating_system import CBLMariner, CpuArchitecture, Oracle, Redhat, Ubuntu
from lisa.tools import Lspci, Lsvmbus, NvidiaSmi
from lisa.tools.lspci import PciDevice
from lisa.util import LisaException, SkippedException, constants

FEATURE_NAME_GPU = "Gpu"


@dataclass_json()
@dataclass()
class GpuSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_GPU
    is_enabled: bool = False

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.is_enabled}"

    def _generate_min_capability(self, capability: Any) -> Any:
        return self


# Link to the latest GRID driver
# The DIR link is
# https://download.microsoft.com/download/9/5/c/95c667ff-ab95-4c56-89e0-e13e9a76782d/NVIDIA-Linux-x86_64-460.32.03-grid-azure.run
DEFAULT_GRID_DRIVER_URL = "https://go.microsoft.com/fwlink/?linkid=874272"

DEFAULT_CUDA_DRIVER_VERSION = "10.1.243-1"


class ComputeSDK(str, Enum):
    GRID = "GRID"
    CUDA = "CUDA"
    AMD = "AMD"


class Gpu(Feature):
    _redhat_gpu_dependencies = [
        "kernel-devel-$(uname -r)",
        "kernel-headers-$(uname -r)",
        "mesa-libGL",
        "mesa-libEGL",
        "libglvnd-devel",
        "dkms",
    ]

    _ubuntu_gpu_dependencies = [
        "build-essential",
        "libelf-dev",
        "linux-tools-$(uname -r)",
        "linux-cloud-tools-$(uname -r)",
    ]

    _oracle_uek_dependencies = [
        "kernel-uek-devel-$(uname -r)",
        "mesa-libGL",
        "mesa-libEGL",
        "libglvnd-devel",
        "dkms",
    ]

    _mariner_dependencies = ["build-essential", "binutils", "kernel-devel"]

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return GpuSettings

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_GPU

    @classmethod
    def can_disable(cls) -> bool:
        return True

    @classmethod
    def remove_virtual_gpus(cls, devices: List[PciDevice]) -> List[PciDevice]:
        return [x for x in devices if x.vendor != "Microsoft Corporation"]

    def enabled(self) -> bool:
        return True

    def is_supported(self) -> bool:
        raise NotImplementedError

    def is_module_loaded(self) -> bool:
        lspci_tool = self._node.tools[Lspci]
        pci_devices = self._get_gpu_from_lspci()
        for device in pci_devices:
            used_module = lspci_tool.get_used_module(device.slot)
            if used_module:
                return True
        return False

    def install_compute_sdk(self, version: str = "") -> None:
        # install GPU dependencies before installing driver
        self._install_gpu_dep()

        # install the driver
        supported_driver = self.get_supported_driver()
        for driver in supported_driver:
            if driver == ComputeSDK.GRID:
                if not version:
                    version = DEFAULT_GRID_DRIVER_URL
                    self._install_grid_driver(version)
            elif driver == ComputeSDK.CUDA:
                if not version:
                    version = DEFAULT_CUDA_DRIVER_VERSION
                    try:
                        self._install_cuda_driver(version)
                    except Exception as e:
                        raise LisaException(f"Failed to install CUDA Driver {str(e)}")
            else:
                raise LisaException(f"{driver} is not a valid value of ComputeSDK")

    def get_gpu_count_with_lsvmbus(self) -> int:
        lsvmbus_device_count = 0
        bridge_device_count = 0

        lsvmbus_tool = self._node.tools[Lsvmbus]
        device_list = lsvmbus_tool.get_device_channels()
        for device in device_list:
            for name, id_, bridge_count in NvidiaSmi.gpu_devices:
                if id_ in device.device_id:
                    lsvmbus_device_count += 1
                    bridge_device_count = bridge_count
                    self._log.debug(f"GPU device {name} found!")
                    break

        return lsvmbus_device_count - bridge_device_count

    def get_gpu_count_with_lspci(self) -> int:
        return len(self._get_gpu_from_lspci())

    def get_gpu_count_with_vendor_cmd(self) -> int:
        nvidiasmi = self._node.tools[NvidiaSmi]
        return nvidiasmi.get_gpu_count()

    def get_supported_driver(self) -> List[ComputeSDK]:
        raise NotImplementedError()

    def _install_driver_using_platform_feature(self) -> None:
        raise NotImplementedError()

    def _get_gpu_from_lspci(self) -> List[PciDevice]:
        lspci_tool = self._node.tools[Lspci]
        device_list = lspci_tool.get_devices_by_type(
            constants.DEVICE_TYPE_GPU, force_run=True
        )
        # Remove Microsoft Virtual one. It presents with GRID driver.
        return self.remove_virtual_gpus(device_list)

    # download and install NVIDIA grid driver
    def _install_grid_driver(self, driver_url: str) -> None:
        self._log.debug("Starting GRID driver installation")
        # download and install the NVIDIA GRID driver
        wget_tool = self._node.tools[Wget]
        grid_file_path = wget_tool.get(
            driver_url,
            str(self._node.working_path),
            "NVIDIA-Linux-x86_64-grid.run",
            executable=True,
        )
        result = self._node.execute(
            f"{grid_file_path} --no-nouveau-check --silent --no-cc-version-check",
            sudo=True,
        )
        result.assert_exit_code(
            0,
            "Failed to install the GRID driver! "
            f"exit-code: {result.exit_code} stderr: {result.stderr}",
        )
        self._log.debug("Successfully installed the GRID driver")

    # download and install CUDA Driver
    def _install_cuda_driver(self, version: str) -> None:
        self._log.debug("Starting CUDA driver installation")
        cuda_repo = ""
        os_information = self._node.os.information

        if isinstance(self._node.os, Redhat):
            release = os_information.release.split(".")[0]
            self._node.os.add_repository(
                "http://developer.download.nvidia.com/compute/cuda/"
                f"repos/rhel{release}/x86_64/cuda-rhel{release}.repo"
            )
            install_packages = ["nvidia-driver-cuda"]
            if release == "7":
                install_packages.append("nvidia-driver-latest-dkms")
            self._node.os.install_packages(install_packages, signed=False)

        elif isinstance(self._node.os, Ubuntu):
            release = re.sub("[^0-9]+", "", os_information.release)
            # there is no ubuntu2110 and ubuntu2104 folder under nvidia site
            if release in ["2110", "2104"]:
                release = "2004"
            # 2210, 2304, 2310 NVIDIA Drivers are not available, use 2204
            if release in ["2210", "2304", "2310"]:
                release = "2204"

            # Public CUDA GPG key is needed to be installed for Ubuntu
            self._node.tools[Wget].get(
                "https://developer.download.nvidia.com/compute/cuda/repos/"
                f"ubuntu{release}/x86_64/cuda-keyring_1.0-1_all.deb"
            )
            self._node.execute(
                "dpkg -i cuda-keyring_1.0-1_all.deb",
                sudo=True,
                cwd=self._node.get_working_path(),
            )

            if release in ["1604"]:
                cuda_repo_pkg = f"cuda-repo-ubuntu{release}_{version}_amd64.deb"
                cuda_repo = (
                    "http://developer.download.nvidia.com/compute/"
                    f"cuda/repos/ubuntu{release}/x86_64/{cuda_repo_pkg}"
                )
                # download and install the cuda driver package from the repo
                self._node.os._install_package_from_url(
                    f"{cuda_repo}", package_name="cuda-drivers.deb", signed=False
                )
            else:
                self._node.tools[Wget].get(
                    f"https://developer.download.nvidia.com/compute/cuda/repos/"
                    f"ubuntu{release}/x86_64/cuda-ubuntu{release}.pin",
                    "/etc/apt/preferences.d",
                    "cuda-repository-pin-600",
                    sudo=True,
                    overwrite=False,
                )
                repo_entry = (
                    f"deb http://developer.download.nvidia.com/compute/cuda/repos/"
                    f"ubuntu{release}/x86_64/ /"
                )
                self._node.execute(
                    f'add-apt-repository -y "{repo_entry}"',
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        f"failed to add repo {repo_entry}"
                    ),
                )
                # the latest version cuda-drivers-510 has issues
                # nvidia-smi
                # No devices were found
                # dmesg
                # NVRM: GPU 0001:00:00.0: RmInitAdapter failed! (0x63:0x55:2344)
                # NVRM: GPU 0001:00:00.0: rm_init_adapter failed, device minor number 0
                cuda_package_versions = {"1804": "530"}
                # 545 is the latest version available for Ubuntu 2004+
                package_version = cuda_package_versions.get(release, "545")
                self._node.os.install_packages(f"cuda-drivers-{package_version}")
        elif (
            isinstance(self._node.os, CBLMariner)
            and self._node.os.get_kernel_information().hardware_platform
            == CpuArchitecture.X64
        ):
            self._node.os.add_repository(
                "https://raw.githubusercontent.com/microsoft/CBL-Mariner/2.0/"
                "toolkit/docs/nvidia/mariner-nvidia.repo"
            )
            self._node.os.install_packages("cuda", signed=False)
        else:
            raise SkippedException(
                f"Distro {self._node.os.name} ver: {self._node.os.information.version}"
                " not supported to install CUDA driver."
            )

    def _install_gpu_dep(self) -> None:
        kernel_ver = self._node.tools[Uname].get_linux_information().kernel_version_raw
        # install dependency libraries for distros
        if isinstance(self._node.os, Redhat):
            self._node.os.install_epel()
            if isinstance(self._node.os, Oracle) and "uek" in kernel_ver:
                self._node.os.install_packages(
                    self._oracle_uek_dependencies, signed=False
                )
            else:
                self._node.os.install_packages(
                    self._redhat_gpu_dependencies, signed=False
                )
            release = self._node.os.information.release.split(".")[0]
            if release == "7":
                # vulkan-filesystem is required by CUDA in CentOS 7.x
                self._node.os._install_package_from_url(
                    "https://vault.centos.org/centos/7/os/x86_64/Packages/"
                    "vulkan-filesystem-1.1.97.0-1.el7.noarch.rpm"
                )

        elif (
            isinstance(self._node.os, Ubuntu)
            and self._node.os.information.version >= "16.4.0"
        ):
            self._node.os.install_packages(self._ubuntu_gpu_dependencies, timeout=2000)
        elif (
            isinstance(self._node.os, CBLMariner)
            and self._node.os.information.version == "2.0.0"
        ):
            self._node.os.install_packages(self._mariner_dependencies, signed=False)
        else:
            raise SkippedException(
                f"Distro {self._node.os.name} ver: {self._node.os.information.version}"
                " is not supported for GPU driver installation."
            )


GpuEnabled = partial(GpuSettings, is_enabled=True)
