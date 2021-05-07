# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from enum import Enum
from typing import Any

from lisa.base_tools.wget import Wget
from lisa.feature import Feature
from lisa.operating_system import Redhat, Ubuntu
from lisa.tools import Uname
from lisa.util import LisaException, SkippedException
from lisa.util.logger import get_logger

FEATURE_NAME_GPU = "Gpu"

ComputeSDK = Enum(
    "ComputeSDK",
    [
        # GRID Driver
        "GRID",
        # CUDA Driver
        "CUDA",
    ],
)

# Link to the latest GRID driver
# The DIR link is
# https://download.microsoft.com/download/9/5/c/95c667ff-ab95-4c56-89e0-e13e9a76782d/NVIDIA-Linux-x86_64-460.32.03-grid-azure.run
DEFAULT_GRID_DRIVER_URL = "https://go.microsoft.com/fwlink/?linkid=874272"


class Gpu(Feature):
    def __init__(self, node: Any, platform: Any) -> None:
        super().__init__(node, platform)
        self._log = get_logger("feature", self.name(), self._node.log)

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_GPU

    def _is_supported(self) -> bool:
        raise NotImplementedError()

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
        os_version = self._node.os.os_version

        if isinstance(self._node.os, Redhat):
            release = os_version.release.split(".")[0]
            cuda_repo_pkg = f"cuda-repo-rhel{release}-{version}.x86_64.rpm"
            cuda_repo = (
                "http://developer.download.nvidia.com/"
                f"compute/cuda/repos/rhel{release}/x86_64/{cuda_repo_pkg}"
            )
        elif isinstance(self._node.os, Ubuntu):
            release = re.sub("[^0-9]+", "", os_version.release)
            cuda_repo_pkg = f"cuda-repo-ubuntu{release}_{version}_amd64.deb"
            cuda_repo = (
                "http://developer.download.nvidia.com/compute/"
                f"cuda/repos/ubuntu{release}/x86_64/{cuda_repo_pkg}"
            )
        else:
            raise LisaException(
                f"Distro {self._node.os.__class__.__name__}"
                "not supported to install CUDA driver."
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
                f"Distro {self._node.os.__class__.__name__}"
                " is not supported for GPU."
            )

    def check_support(self) -> None:
        # TODO: more supportability can be defined here
        if not self._is_supported():
            raise SkippedException(f"GPU is not supported with distro {self._node.os}")

    def install_compute_sdk(
        self, driver: ComputeSDK = ComputeSDK.CUDA, version: str = ""
    ) -> None:
        # install GPU dependencies before installing driver
        self._install_gpu_dep()

        # install the driver
        if driver == ComputeSDK.GRID:
            if version == "":
                version = DEFAULT_GRID_DRIVER_URL
            self._install_grid_driver(version)
        elif driver == ComputeSDK.CUDA:
            if version == "":
                version = "10.1.105-1"
            self._install_cuda_driver(version)
        else:
            raise LisaException(
                f"{ComputeSDK} is invalid."
                "No valid driver SDK name provided to install."
            )
