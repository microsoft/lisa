# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from abc import abstractmethod
from typing import Any, List, Optional

from lisa.base_tools import Wget
from lisa.base_tools.uname import Uname
from lisa.executable import Tool
from lisa.features import Gpu
from lisa.features.gpu import ComputeSDK
from lisa.operating_system import (
    CBLMariner,
    CpuArchitecture,
    Oracle,
    Posix,
    Redhat,
    Ubuntu,
)
from lisa.tools import Df
from lisa.tools.amdsmi import AmdSmi
from lisa.tools.nvidiasmi import NvidiaSmi
from lisa.util import LisaException, MissingPackagesException, SkippedException


class GpuDriver(Tool):
    """
    Virtual tool that wraps GPU-specific monitoring tools (NvidiaSmi, AmdSmi).
    """

    @property
    def command(self) -> str:
        return "echo"

    @property
    def can_install(self) -> bool:
        return False

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        Determine which GPU vendor is present and set the appropriate monitoring tool.
        This runs once when the tool is first accessed.
        """
        gpu = self.node.features[Gpu]
        supported_drivers = gpu.get_supported_driver()

        # Determine GPU vendor type and set the appropriate monitoring tool
        if ComputeSDK.AMD in supported_drivers:
            self._monitoring_tool = self.node.tools[AmdSmi]
            self._supported_drivers = supported_drivers
            self._log.debug(
                f"GPU vendor detected: AMD (supported drivers: {supported_drivers})"
            )
        elif (
            ComputeSDK.CUDA in supported_drivers or ComputeSDK.GRID in supported_drivers
        ):
            self._monitoring_tool = self.node.tools[NvidiaSmi]
            self._supported_drivers = supported_drivers
            self._log.debug(
                f"GPU vendor detected: NVIDIA (supported drivers: {supported_drivers})"
            )
        else:
            raise SkippedException(
                f"No supported GPU driver type found: {supported_drivers}"
            )

    def get_gpu_count(self) -> int:
        return self._monitoring_tool.get_gpu_count()

    def install_driver(self) -> None:
        for driver_type in self._supported_drivers:
            if driver_type == ComputeSDK.GRID:
                self.node.log.info("Installing NVIDIA GRID driver")
                from lisa.tools.gpu_drivers import NvidiaGridDriver

                _ = self.node.tools[NvidiaGridDriver]
            elif driver_type == ComputeSDK.CUDA:
                self.node.log.info("Installing NVIDIA CUDA driver")
                from lisa.tools.gpu_drivers import NvidiaCudaDriver

                _ = self.node.tools[NvidiaCudaDriver]
            elif driver_type == ComputeSDK.AMD:
                self.node.log.info("Installing AMD GPU driver")
                from lisa.tools.gpu_drivers import AmdGpuDriver

                _ = self.node.tools[AmdGpuDriver]
            else:
                raise LisaException(f"Unsupported driver type: '{driver_type}'")

        self.node.log.debug(
            f"{self._supported_drivers} driver installed. "
            "Reboot required to load driver."
        )


class GpuDriverInstaller(Tool):
    """
    Base class for GPU driver installation tools.
    Handles common patterns for GPU driver installation across different vendors.
    """

    @property
    @abstractmethod
    def driver_name(self) -> str:
        """Return the human-readable driver name (e.g., 'NVIDIA GRID', 'NVIDIA CUDA')"""
        raise NotImplementedError

    @property
    @abstractmethod
    def command(self) -> str:
        """
        Return the verification command to check if driver is working.
        """
        raise NotImplementedError

    @property
    def can_install(self) -> bool:
        return True

    def get_version(self) -> str:
        """Get the currently installed driver version"""
        result = self.node.execute(f"{self.command} --version", shell=True, sudo=True)
        return result.stdout.strip()

    @abstractmethod
    def _get_os_dependencies(self) -> List[str]:
        """
        Return OS-specific package dependencies needed before driver installation.
        Override this method to provide distro-specific dependencies.
        """
        raise NotImplementedError

    @abstractmethod
    def _is_os_supported(self) -> bool:
        """
        Check if the current OS/version is supported for this driver.
        Override this method to specify OS compatibility.
        """
        raise NotImplementedError

    def _install_dependencies(self) -> None:
        """
        Install all required dependencies for driver installation.

        Default implementation just installs packages from _get_os_dependencies().
        Override this method if you need custom dependency installation logic.
        """
        dependencies = self._get_os_dependencies()
        if not dependencies:
            return

        self._log.debug(f"Installing {self.driver_name} dependencies: {dependencies}")

        assert isinstance(
            self.node.os, Posix
        ), "GPU driver installation is only implemented for POSIX systems"

        # Install EPEL for RedHat family if needed
        if isinstance(self.node.os, Redhat):
            self.node.os.install_epel()

        self.node.os.install_packages(dependencies, signed=False)

    def _install(self) -> bool:
        """
        Main installation workflow.
        1. Check OS support
        2. Install dependencies
        3. Install driver (implemented by subclass)
        """
        if not self._is_os_supported():
            raise SkippedException(
                f"{self.driver_name} is not supported on "
                f"{self.node.os.name} {self.node.os.information.version}"
            )

        self._log.info(f"Starting {self.driver_name} installation")

        self._install_dependencies()
        self._install_driver()
        self._log.info(f"{self.driver_name} installation completed successfully")

        version = self.get_version()
        self._log.info(f"Installed {self.driver_name} \n {version}")

        return True

    @abstractmethod
    def _install_driver(self) -> None:
        """
        Install the actual GPU driver.
        Must be implemented by subclass to handle driver-specific installation.
        """
        raise NotImplementedError


class NvidiaGridDriver(GpuDriverInstaller):
    """
    NVIDIA GRID driver installer for GPU-enabled VMs.

    GRID drivers are typically used for graphics and visualization workloads
    on VMs with Tesla M60, Tesla T4, or similar GPUs.

    Reference:
    https://learn.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup#nvidia-grid-drivers
    """

    DEFAULT_GRID_DRIVER_URL = "https://go.microsoft.com/fwlink/?linkid=874272"

    # GRID driver is only supported on specific OS versions
    _SUPPORTED_DISTROS = {
        Redhat: ["7.9.0", "8.6.0", "8.8.0", "9.0.0", "9.2.0"],
        Ubuntu: ["20.4.0", "22.4.0"],
    }

    @property
    def driver_name(self) -> str:
        return "NVIDIA GRID"

    @property
    def command(self) -> str:
        return "nvidia-smi"

    def _is_os_supported(self) -> bool:
        """GRID drivers have limited OS support"""
        version = str(self.node.os.information.version)

        if isinstance(self.node.os, Redhat):
            return version in self._SUPPORTED_DISTROS[Redhat]
        elif isinstance(self.node.os, Ubuntu):
            return version in self._SUPPORTED_DISTROS[Ubuntu]

        return False

    def _get_os_dependencies(self) -> List[str]:
        """Get dependencies based on OS type"""
        kernel_ver = self.node.tools[Uname].get_linux_information().kernel_version_raw

        # Oracle Linux with UEK kernel has different requirements
        if isinstance(self.node.os, Oracle) and "uek" in kernel_ver:
            return [
                "kernel-uek-devel-$(uname -r)",
                "mesa-libGL",
                "mesa-libEGL",
                "libglvnd-devel",
                "dkms",
            ]

        # RedHat family dependencies
        if isinstance(self.node.os, Redhat):
            return [
                "kernel-devel-$(uname -r)",
                "kernel-headers-$(uname -r)",
                "mesa-libGL",
                "mesa-libEGL",
                "libglvnd-devel",
                "dkms",
            ]

        # Ubuntu dependencies
        if isinstance(self.node.os, Ubuntu):
            return [
                "build-essential",
                "libelf-dev",
                "linux-tools-$(uname -r)",
                "linux-cloud-tools-$(uname -r)",
            ]

        return []

    def _install_driver(self, driver_url: Optional[str] = None) -> None:
        """Download and install NVIDIA GRID driver"""
        if not driver_url:
            driver_url = self.DEFAULT_GRID_DRIVER_URL

        self._log.debug(f"Downloading GRID driver from {driver_url}")

        wget_tool = self.node.tools[Wget]
        grid_file_path = wget_tool.get(
            driver_url,
            str(self.node.working_path),
            "NVIDIA-Linux-x86_64-grid.run",
            executable=True,
        )

        result = self.node.execute(
            f"{grid_file_path} --no-nouveau-check --silent --no-cc-version-check",
            sudo=True,
            timeout=600,  # Installation can take time
        )

        result.assert_exit_code(
            0,
            f"Failed to install GRID driver! "
            f"exit-code: {result.exit_code} stderr: {result.stderr}",
        )

        self._log.info("Successfully installed NVIDIA GRID driver")


class NvidiaCudaDriver(GpuDriverInstaller):
    """
    NVIDIA CUDA driver installer for GPU compute workloads.

    CUDA drivers are used for general purpose GPU computing on Tesla GPUs
    (K80, P100, V100, P40, etc.).

    Reference:
    https://learn.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup#nvidia-cuda-drivers
    """

    DEFAULT_CUDA_VERSION = "10.1.243-1"

    @property
    def driver_name(self) -> str:
        return "NVIDIA CUDA"

    @property
    def command(self) -> str:
        return "nvidia-smi"

    def _is_os_supported(self) -> bool:
        """CUDA drivers support a wider range of OS versions"""
        os_info = self.node.os.information

        if isinstance(self.node.os, Redhat):
            return bool(os_info.version >= "7.0.0")
        elif isinstance(self.node.os, Ubuntu):
            return bool(os_info.version >= "16.4.0")
        elif isinstance(self.node.os, CBLMariner):
            return bool(os_info.version >= "2.0.0")

        return False

    def _get_os_dependencies(self) -> List[str]:
        """Get dependencies based on OS type"""
        kernel_ver = self.node.tools[Uname].get_linux_information().kernel_version_raw

        # Oracle Linux with UEK kernel
        if isinstance(self.node.os, Oracle) and "uek" in kernel_ver:
            return [
                "kernel-uek-devel-$(uname -r)",
                "mesa-libGL",
                "mesa-libEGL",
                "libglvnd-devel",
                "dkms",
            ]

        # RedHat family dependencies
        if isinstance(self.node.os, Redhat):
            deps = [
                "kernel-devel-$(uname -r)",
                "kernel-headers-$(uname -r)",
                "mesa-libGL",
                "mesa-libEGL",
                "libglvnd-devel",
                "dkms",
            ]
            # CentOS/RHEL 7 needs additional package
            release = self.node.os.information.release.split(".")[0]
            if release == "7":
                deps.append("nvidia-driver-latest-dkms")
            return deps

        # Ubuntu dependencies
        if isinstance(self.node.os, Ubuntu):
            return [
                "build-essential",
                "libelf-dev",
                "linux-tools-$(uname -r)",
                "linux-cloud-tools-$(uname -r)",
            ]

        # CBL-Mariner dependencies
        if isinstance(self.node.os, CBLMariner):
            return ["build-essential", "binutils", "kernel-devel"]

        return []

    def _install_dependencies(self) -> None:
        """
        Install CUDA driver dependencies with special handling for CentOS 7.
        Overrides base class to add vulkan-filesystem for CentOS 7.x.
        """
        # Call parent to install standard dependencies
        super()._install_dependencies()

        if isinstance(self.node.os, Redhat):
            release = self.node.os.information.release.split(".")[0]
            if release == "7":
                assert isinstance(self.node.os, Posix)
                self._log.debug("Installing vulkan-filesystem for CentOS 7")
                self.node.os._install_package_from_url(
                    "https://vault.centos.org/centos/7/os/x86_64/Packages/"
                    "vulkan-filesystem-1.1.97.0-1.el7.noarch.rpm"
                )

    def _install_driver(self) -> None:
        """Install CUDA driver based on OS"""
        if isinstance(self.node.os, Redhat):
            self._install_cuda_redhat()
        elif isinstance(self.node.os, Ubuntu):
            self._install_cuda_ubuntu()
        elif isinstance(self.node.os, CBLMariner):
            self._install_cuda_mariner()
        else:
            raise SkippedException(
                f"CUDA installation not supported on {self.node.os.name}"
            )

    def _install_cuda_redhat(self) -> None:
        """Install CUDA driver on RedHat family distributions"""
        self._log.debug("Installing CUDA driver for RedHat")

        assert isinstance(self.node.os, Posix), "CUDA installation requires Posix OS"

        release = self.node.os.information.release.split(".")[0]

        # Add CUDA repository
        self.node.os.add_repository(
            f"http://developer.download.nvidia.com/compute/cuda/"
            f"repos/rhel{release}/x86_64/cuda-rhel{release}.repo"
        )

        # Install CUDA packages
        packages = ["nvidia-driver-cuda"]
        if release == "7":
            packages.append("nvidia-driver-latest-dkms")

        self.node.os.install_packages(packages, signed=False)
        self._log.info(f"Successfully installed CUDA driver packages: {packages}")

    def _install_cuda_ubuntu(self) -> None:
        """Install CUDA driver on Ubuntu"""
        self._log.debug("Installing CUDA driver for Ubuntu")

        assert isinstance(self.node.os, Posix), "CUDA installation requires Posix OS"

        cuda_package_name = "cuda-drivers"
        cuda_drivers_package_pattern = re.compile(
            r"^cuda-drivers-(\d+)/.*$", re.MULTILINE
        )

        os_info = self.node.os.information
        release = re.sub("[^0-9]+", "", os_info.release)

        # Handle unsupported releases by using closest supported version
        if release in ["2110", "2104"]:
            release = "2004"
        if release in ["2210", "2304", "2310"]:
            release = "2204"

        # Install CUDA public GPG key
        cuda_keyring = "cuda-keyring_1.1-1_all.deb"
        self.node.tools[Wget].get(
            f"https://developer.download.nvidia.com/compute/cuda/repos/"
            f"ubuntu{release}/x86_64/{cuda_keyring}"
        )
        self.node.execute(
            f"dpkg -i {cuda_keyring}",
            sudo=True,
            cwd=self.node.get_working_path(),
        )

        # For Ubuntu 16.04, use legacy installation method
        if release == "1604":
            cuda_repo_pkg = (
                f"cuda-repo-ubuntu{release}_" f"{self.DEFAULT_CUDA_VERSION}_amd64.deb"
            )
            cuda_repo = (
                f"http://developer.download.nvidia.com/compute/cuda/repos/"
                f"ubuntu{release}/x86_64/{cuda_repo_pkg}"
            )
            self.node.os._install_package_from_url(
                cuda_repo, package_name="cuda-drivers.deb", signed=False
            )
        else:
            # Modern Ubuntu versions
            self.node.tools[Wget].get(
                f"https://developer.download.nvidia.com/compute/cuda/repos/"
                f"ubuntu{release}/x86_64/cuda-ubuntu{release}.pin",
                "/etc/apt/preferences.d",
                "cuda-repository-pin-600",
                sudo=True,
                overwrite=False,
            )

            # Add CUDA repository
            repo_entry = (
                f"deb http://developer.download.nvidia.com/compute/cuda/repos/"
                f"ubuntu{release}/x86_64/ /"
            )
            self.node.execute(
                f'add-apt-repository -y "{repo_entry}"',
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=f"failed to add repo {repo_entry}",
            )

            # Find available CUDA driver versions
            result = self.node.execute(f"apt search {cuda_package_name}", sudo=True)
            available_versions = cuda_drivers_package_pattern.findall(result.stdout)

            if available_versions:
                # Sort versions and select the highest one
                highest_version = max(available_versions, key=int)
                package_name = f"{cuda_package_name}-{highest_version}"
            else:
                raise MissingPackagesException([cuda_package_name])

            self.node.os.install_packages(package_name)

        self._log.info("Successfully installed CUDA driver for Ubuntu")

    def _install_cuda_mariner(self) -> None:
        """Install CUDA driver on CBL-Mariner"""
        self._log.debug("Installing CUDA driver for CBL-Mariner")

        assert isinstance(self.node.os, Posix), "CUDA installation requires Posix OS"

        hw_platform = self.node.os.get_kernel_information().hardware_platform
        if hw_platform != CpuArchitecture.X64:
            raise SkippedException("CUDA driver only supported on x64 architecture")

        # Add Mariner NVIDIA repository
        self.node.os.add_repository(
            "https://raw.githubusercontent.com/microsoft/CBL-Mariner/2.0/"
            "toolkit/docs/nvidia/mariner-nvidia.repo"
        )

        # Install CUDA
        self.node.os.install_packages("cuda", signed=False)
        self._log.info("Successfully installed CUDA driver for CBL-Mariner")


class AmdGpuDriver(GpuDriverInstaller):
    """
    AMD GPU driver installer with ROCm support.

    Supported Operating Systems:
    - Ubuntu 22.04 (Jammy)
    - Ubuntu 24.04 (Noble)

    Reference:
    https://learn.microsoft.com/en-us/azure/virtual-machines/linux/azure-n-series-amd-gpu-driver-linux-installation-guide
    """

    # ROCm version to install
    ROCM_VERSION = "7.0.1"
    ROCM_BUILD = "70001"

    @property
    def driver_name(self) -> str:
        return "AMD GPU (ROCm)"

    @property
    def command(self) -> str:
        return "amd-smi"

    def get_version(self) -> str:
        """Get the currently installed AMD driver version"""
        result = self.node.execute(f"{self.command} version", shell=True, sudo=True)
        return result.stdout.strip()

    def _is_os_supported(self) -> bool:
        """
        AMD ROCm drivers are supported on Ubuntu 22.04 and 24.04.
        """
        return isinstance(self.node.os, Ubuntu) and bool(
            self.node.os.information.version >= "22.4.0"
        )

    def _get_os_dependencies(self) -> List[str]:
        """
        Get dependencies for AMD GPU driver installation.
        Same dependencies for both Ubuntu 22.04 and 24.04.
        """
        return [
            "linux-headers-$(uname -r)",
            "linux-modules-extra-$(uname -r)",
            "python3-setuptools",
            "python3-wheel",
        ]

    def _install_driver(self) -> None:
        """
        Install AMD GPU (ROCm) driver on Ubuntu.
        """
        # Type assertion: GPU drivers only run on Linux/Posix systems
        assert isinstance(self.node.os, Posix), "AMD GPU drivers require a Posix OS"

        # Clean up before checking disk space
        self._log.debug("Cleaning package cache and temp files before installation")
        self.node.os.clean_package_cache()

        # Check available disk space (DKMS compilation requires significant space)
        df_tool = self.node.tools[Df]
        root_partition = df_tool.get_partition_by_mountpoint("/", force_run=True)

        if root_partition:
            available_gb = root_partition.available_blocks / (1024 * 1024)
            self._log.debug(
                f"Disk space: / partition has "
                f"{available_gb:.2f} GB available "
                f"({root_partition.percentage_blocks_used}% used)"
            )

            if available_gb < 15:
                raise LisaException(
                    f"Insufficient disk space for AMD GPU driver installation. "
                    f"Available: {available_gb:.2f} GB after cleanup, "
                    f"Required: ~15 GB minimum. "
                    f"DKMS kernel module compilation requires significant "
                    f"temporary space. Please increase the OS disk size to "
                    f"at least 50 GB."
                )

            self._log.info(f"Disk space check passed: {available_gb:.2f} GB available")

        os_info = self.node.os.information
        codename = os_info.codename.lower()

        self._log.info(f"Installing AMD GPU driver for Ubuntu {codename}")

        # Download and install the amdgpu-install package
        installer_url = (
            f"https://repo.radeon.com/amdgpu-install/{self.ROCM_VERSION}/"
            f"ubuntu/{codename}/amdgpu-install_{self.ROCM_VERSION}."
            f"{self.ROCM_BUILD}-1_all.deb"
        )

        self._log.debug(
            f"Downloading and installing AMD GPU installer from {installer_url}"
        )
        assert isinstance(self.node.os, Posix), "AMD GPU installation requires Posix OS"

        # Download the installer .deb file
        wget_tool = self.node.tools[Wget]
        installer_deb = wget_tool.get(
            installer_url,
            str(self.node.working_path),
            f"amdgpu-install_{self.ROCM_VERSION}.{self.ROCM_BUILD}-1_all.deb",
        )

        # Install using dpkg
        result = self.node.execute(
            f"dpkg -i {installer_deb}",
            sudo=True,
            timeout=300,
        )
        result.assert_exit_code(
            0,
            f"Failed to install amdgpu-install package! "
            f"exit-code: {result.exit_code} stderr: {result.stderr}",
        )

        # Update package cache after adding AMD repositories
        self._log.debug("Updating package cache after adding AMD repositories")
        assert isinstance(self.node.os, Ubuntu), "AMD GPU driver only supports Ubuntu"
        self.node.os._initialize_package_installation()

        # Install amdgpu-dkms and rocm
        self._log.info("Installing amdgpu-dkms and rocm")
        self.node.os.install_packages(
            ["amdgpu-dkms", "rocm"],
            signed=False,
            timeout=1800,  # Can take up to 30 minutes
        )

        # Verify DKMS build succeeded
        dkms_status = self.node.execute("dkms status amdgpu", sudo=True)
        if "installed" not in dkms_status.stdout.lower():
            self._log.info(f"DKMS build may have failed. Status: {dkms_status.stdout}")

            # Check for the kernel module
            kernel_version = (
                self.node.tools[Uname].get_linux_information().kernel_version_raw
            )
            self.node.execute(
                f"ls -lh /lib/modules/{kernel_version}/updates/dkms/"
                f"amdgpu.ko* 2>&1",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="amdgpu kernel module not found",
            )

        # Clean up package cache to free disk space
        self._log.debug("Cleaning up package cache to free disk space")
        self.node.os.clean_package_cache()

        # Check final disk space
        root_partition = df_tool.get_partition_by_mountpoint("/", force_run=True)
        if root_partition:
            available_gb = root_partition.available_blocks / (1024 * 1024)
            self._log.debug(
                f"Disk space after installation: / partition has "
                f"{available_gb:.2f} GB available "
                f"({root_partition.percentage_blocks_used}% used)"
            )

        self._log.info(
            "Successfully installed AMD GPU (ROCm) driver. "
            "Reboot required to load the driver."
        )
