# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from enum import Enum
from typing import Any, List, Set

from lisa.base_tools import Uname, Wget
from lisa.feature import Feature
from lisa.operating_system import Redhat, Ubuntu
from lisa.sut_orchestrator.azure.tools import LisDriver
from lisa.tools import Lsmod, Lspci, Lsvmbus
from lisa.util import LisaException

FEATURE_NAME_GPU = "Gpu"

# Link to the latest GRID driver
# The DIR link is
# https://download.microsoft.com/download/9/5/c/95c667ff-ab95-4c56-89e0-e13e9a76782d/NVIDIA-Linux-x86_64-460.32.03-grid-azure.run
DEFAULT_GRID_DRIVER_URL = "https://go.microsoft.com/fwlink/?linkid=874272"


class ComputeSDK(Enum):
    # GRID Driver
    GRID = 1
    # CUDA Driver
    CUDA = 2


class Gpu(Feature):
    # tuple of gpu device names and their device id pattern
    # e.g. Tesla GPU device has device id "47505500-0001-0000-3130-444531303244"
    gpu_devices = (("Tesla", "47505500", 0), ("A100-SXM4", "44450000", 6))

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_GPU

    @classmethod
    def enabled(cls) -> bool:
        return True

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def is_supported(self) -> bool:
        raise NotImplementedError

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.gpu_vendor: Set[str] = set()

    def _get_supported_driver(self) -> List[ComputeSDK]:
        raise NotImplementedError

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
            f"{grid_file_path} --no-nouveau-check --silent --no-cc-version-check"
        )
        if result.exit_code != 0:
            raise LisaException(
                "Failed to install the GRID driver! "
                f"exit-code: {result.exit_code} stderr: {result.stderr}"
            )

        self._log.debug("Successfully installed the GRID driver")

    # download and install CUDA Driver
    def _install_cuda_driver(self, version: str) -> None:
        self._log.debug("Starting CUDA driver installation")
        cuda_repo = ""
        os_information = self._node.os.information

        if isinstance(self._node.os, Redhat):
            release = os_information.release.split(".")[0]
            cuda_repo_pkg = f"cuda-repo-rhel{release}-{version}.x86_64.rpm"
            cuda_repo = (
                "http://developer.download.nvidia.com/"
                f"compute/cuda/repos/rhel{release}/x86_64/{cuda_repo_pkg}"
            )
        elif isinstance(self._node.os, Ubuntu):
            release = re.sub("[^0-9]+", "", os_information.release)
            cuda_repo_pkg = f"cuda-repo-ubuntu{release}_{version}_amd64.deb"
            cuda_repo = (
                "http://developer.download.nvidia.com/compute/"
                f"cuda/repos/ubuntu{release}/x86_64/{cuda_repo_pkg}"
            )
        else:
            raise LisaException(
                f"Distro {self._node.os.name}" "not supported to install CUDA driver."
            )

        # download and install the cuda driver package from the repo
        self._node.os._install_package_from_url(f"{cuda_repo}", signed=False)

    def _install_gpu_dep(self) -> None:
        uname_tool = self._node.tools[Uname]
        uname_ver = uname_tool.get_linux_information().uname_version

        # install dependency libraries for distros
        if isinstance(self._node.os, Redhat):
            # install the kernel-devel and kernel-header packages
            package_name = f"kernel-devel-{uname_ver} kernel-headers-{uname_ver}"
            self._node.os.install_packages(package_name)
            # mesa-libEGL install/update is require to avoid a conflict between
            # libraries - bugzilla.redhat 1584740
            package_name = "mesa-libGL mesa-libEGL libglvnd-devel"
            self._node.os.install_packages(package_name)
            # install dkms
            package_name = "dkms"
            self._node.os.install_packages(package_name, signed=False)
        elif isinstance(self._node.os, Ubuntu):
            package_name = (
                f"build-essential libelf-dev linux-tools-{uname_ver}"
                f" linux-cloud-tools-{uname_ver} python libglvnd-dev ubuntu-desktop"
            )
            self._node.os.install_packages(package_name)
        else:
            raise LisaException(
                f"Distro {self._node.os.name} is not supported for GPU."
            )

    def is_module_loaded(self) -> bool:
        lsmod_tool = self._node.tools[Lsmod]
        if (len(self.gpu_vendor) > 0) and all(
            lsmod_tool.module_exists(vendor) for vendor in self.gpu_vendor
        ):
            return True

        return False

    def install_compute_sdk(self, version: str = "") -> None:
        # install GPU dependencies before installing driver
        self._install_gpu_dep()

        if isinstance(self._node.os, Redhat):
            # install LIS driver if not already installed.
            self._node.tools[LisDriver]

        # install the driver
        supported_driver = self._get_supported_driver()
        for driver in supported_driver:
            if driver == ComputeSDK.GRID:
                if not version:
                    version = DEFAULT_GRID_DRIVER_URL
                    self._install_grid_driver(version)
                    self.gpu_vendor.add("nvidia")
            elif driver == ComputeSDK.CUDA:
                if not version:
                    version = "10.1.105-1"
                    self._install_cuda_driver(version)
                    self.gpu_vendor.add("nvidia")
            else:
                raise LisaException(f"{driver} is not a valid value of ComputeSDK")

        if not self.gpu_vendor:
            raise LisaException("No supported gpu driver/vendor found for this node.")

    def get_gpu_count_with_lsvmbus(self) -> int:
        lsvmbus_device_count = 0
        extra_device_count = 0

        lsvmbus_tool = self._node.tools[Lsvmbus]
        device_list = lsvmbus_tool.get_device_channels_from_lsvmbus()
        for device in device_list:
            for name, id, extra_count in self.gpu_devices:
                if id in device.device_id:
                    lsvmbus_device_count += 1
                    extra_device_count = extra_count
                    self._log.debug(f"GPU device {name} found!")
                    break

        return lsvmbus_device_count - extra_device_count

    def get_gpu_count_with_lspci(self) -> int:
        lspci_device_count = 0
        extra_device_count = 0

        lspci_tool = self._node.tools[Lspci]
        device_list = lspci_tool.get_device_list()
        for device in device_list:
            for name, id, extra_count in self.gpu_devices:
                if name in device.device_info:
                    lspci_device_count += 1
                    extra_device_count = extra_count
                    self._log.debug(f"GPU device with device Id pattern - {id} found!")
                    break

        return lspci_device_count - extra_device_count

    def get_gpu_count_with_vendor_cmd(self) -> int:
        device_count = 0

        if "nvidia" in self.gpu_vendor:
            result = self._node.execute("nvidia-smi")
            if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
                raise LisaException(
                    f"nvidia-smi command exited with exit_code {result.exit_code}"
                )
            for device_info in result.stdout.splitlines():
                if any(device_info in device_name for device_name in self.gpu_devices):
                    device_count += 1

        return device_count
