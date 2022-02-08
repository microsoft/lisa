# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from enum import Enum
from typing import Any, List, Set

from lisa.base_tools import Wget
from lisa.feature import Feature
from lisa.operating_system import Redhat, Ubuntu
from lisa.sut_orchestrator.azure.tools import LisDriver
from lisa.tools import Lsmod, Lspci, Lsvmbus
from lisa.util import LisaException, constants

FEATURE_NAME_GPU = "Gpu"

# Link to the latest GRID driver
# The DIR link is
# https://download.microsoft.com/download/9/5/c/95c667ff-ab95-4c56-89e0-e13e9a76782d/NVIDIA-Linux-x86_64-460.32.03-grid-azure.run
DEFAULT_GRID_DRIVER_URL = "https://go.microsoft.com/fwlink/?linkid=874272"

DEFAULT_CUDA_DRIVER_VERSION = "10.1.105-1"


class ComputeSDK(Enum):
    # GRID Driver
    GRID = 1
    # CUDA Driver
    CUDA = 2


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
        "python",
        "libglvnd-dev",
        "ubuntu-desktop",
    ]

    # tuple of gpu device names and their device id pattern
    # e.g. Tesla GPU device has device id "47505500-0001-0000-3130-444531303244"
    gpu_devices = (("Tesla", "47505500", 0), ("A100", "44450000", 6))

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
            # download and install the cuda driver package from the repo
            self._node.os._install_package_from_url(
                f"{cuda_repo}", package_name="cuda-drivers.rpm", signed=False
            )
        elif isinstance(self._node.os, Ubuntu):
            release = re.sub("[^0-9]+", "", os_information.release)
            # Public CUDA GPG key is needed to be installed for Ubuntu
            self._node.execute(
                "apt-key adv --fetch-keys http://developer.download.nvidia.com/compute/"
                f"cuda/repos/ubuntu{release}/x86_64/7fa2af80.pub",
                sudo=True,
            )
            if "1804" == release:
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
                #  switch to use 495
                self._node.os.install_packages("cuda-drivers-495")
        else:
            raise LisaException(
                f"Distro {self._node.os.name}" "not supported to install CUDA driver."
            )

    def _install_gpu_dep(self) -> None:
        # install dependency libraries for distros
        if isinstance(self._node.os, Redhat):
            self._node.os.install_packages(
                list(self._redhat_gpu_dependencies), signed=False
            )
        elif isinstance(self._node.os, Ubuntu):
            self._node.os.install_packages(list(self._ubuntu_gpu_dependencies))
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
        try:
            # install LIS driver if required and not already installed.
            if LisDriver.can_install:
                self._node.tools[LisDriver]
        except Exception as identifier:
            self._log.debug(
                "LisDriver is not installed. It might not be required. " f"{identifier}"
            )

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
                    version = DEFAULT_CUDA_DRIVER_VERSION
                    self._install_cuda_driver(version)
                    self.gpu_vendor.add("nvidia")
            else:
                raise LisaException(f"{driver} is not a valid value of ComputeSDK")

        if not self.gpu_vendor:
            raise LisaException("No supported gpu driver/vendor found for this node.")

    def get_gpu_count_with_lsvmbus(self) -> int:
        lsvmbus_device_count = 0
        bridge_device_count = 0

        lsvmbus_tool = self._node.tools[Lsvmbus]
        device_list = lsvmbus_tool.get_device_channels()
        for device in device_list:
            for name, id, bridge_count in self.gpu_devices:
                if id in device.device_id:
                    lsvmbus_device_count += 1
                    bridge_device_count = bridge_count
                    self._log.debug(f"GPU device {name} found!")
                    break

        return lsvmbus_device_count - bridge_device_count

    def get_gpu_count_with_lspci(self) -> int:
        lspci_tool = self._node.tools[Lspci]
        device_list = lspci_tool.get_device_list_per_device_type(
            constants.DEVICE_TYPE_GPU
        )

        return len(device_list)

    def get_gpu_count_with_vendor_cmd(self) -> int:
        device_count = 0

        if "nvidia" in self.gpu_vendor:
            # sample output
            # GPU 0: Tesla P100-PCIE-16GB (UUID: GPU-0609318e-4920-44d8-a9fd-7bae639f7c5d)# noqa: E501
            # GPU 1: Tesla P100-PCIE-16GB (UUID: GPU-ede45443-35ad-8d4e-f40d-988423bc6c0b)# noqa: E501
            # GPU 2: Tesla P100-PCIE-16GB (UUID: GPU-ccd6174e-b288-b73c-682e-054c83ef3a3e)# noqa: E501
            # GPU 3: Tesla P100-PCIE-16GB (UUID: GPU-225b4607-ceba-5806-d41a-49ccbcf9794d)# noqa: E501
            result = self._node.execute("nvidia-smi -L", shell=True)
            if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
                raise LisaException(
                    f"nvidia-smi command exited with exit_code {result.exit_code}"
                )
            gpu_types = [x[0] for x in self.gpu_devices]
            for gpu_type in gpu_types:
                device_count += result.stdout.count(gpu_type)

        return device_count
