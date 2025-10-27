# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from abc import abstractmethod
from typing import List, Optional

from lisa.base_tools import Wget
from lisa.base_tools.uname import Uname
from lisa.executable import Tool
from lisa.operating_system import (
    CBLMariner,
    CpuArchitecture,
    Oracle,
    Posix,
    Redhat,
    Ubuntu,
)
from lisa.tools.whoami import Whoami
from lisa.util import MissingPackagesException, SkippedException


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
    def command(self) -> str:
        """
        Return the verification command to check if driver is working.
        """
        raise NotImplementedError

    @property
    def can_install(self) -> bool:
        return True

    def get_installed_version(self, force_run: bool = False) -> str:
        """Get the currently installed driver version"""
        result = self.node.execute(f"{self.command} --version", shell=True, sudo=True)
        if result.exit_code == 0:
            return result.stdout.strip()
        return ""

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

        # Ensure we're on a Posix system (all GPU drivers require Linux)
        assert isinstance(self.node.os, Posix), "GPU drivers require a Posix OS"

        # Install EPEL for RedHat family if needed
        if isinstance(self.node.os, Redhat):
            self.node.os.install_epel()

        # Install the dependency packages
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

        # Install dependencies first
        self._install_dependencies()

        # Install the actual driver (implemented by subclass)
        self._install_driver()

        return self._check_exists()

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

    def _is_os_supported(self) -> bool:
        """GRID drivers have limited OS support"""
        os_type = type(self.node.os)
        if os_type not in self._SUPPORTED_DISTROS:
            return False

        version = str(self.node.os.information.version)
        return version in self._SUPPORTED_DISTROS[os_type]

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

        self._log.debug("Installing GRID driver (this may take several minutes)...")

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

    def install_with_url(self, driver_url: str) -> None:
        """
        Install GRID driver from a specific URL.
        Useful for testing or custom driver versions.
        """
        if self._check_exists():
            self._log.debug("GRID driver already installed")
            return

        if not self._is_os_supported():
            raise SkippedException(
                f"GRID driver not supported on "
                f"{self.node.os.name} {self.node.os.information.version}"
            )

        self._install_dependencies()
        self._install_driver(driver_url)


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

    def _is_os_supported(self) -> bool:
        """CUDA drivers support a wider range of OS versions"""
        os_info = self.node.os.information

        if isinstance(self.node.os, Redhat):
            return os_info.version >= "7.0.0"
        elif isinstance(self.node.os, Ubuntu):
            return os_info.version >= "16.4.0"
        elif isinstance(self.node.os, CBLMariner):
            return os_info.version >= "2.0.0"

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

        # Special handling for RedHat 7 vulkan-filesystem
        # vulkan-filesystem is required by CUDA in CentOS/RHEL 7.x
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

    Installs AMD GPU drivers for Radeon PRO V710 and similar GPUs.

    Supported Operating Systems:
    - Ubuntu 22.04 (Jammy)
    - Ubuntu 24.04 (Noble)

    Reference:
    https://learn.microsoft.com/en-us/azure/virtual-machines/linux/azure-n-series-amd-gpu-driver-linux-installation-guide
    """

    # ROCm version to install
    ROCM_VERSION = "7.0.1"
    ROCM_BUILD = "70001"

    # AMD GPU Device ID for V710
    AMD_V710_DEVICE_ID = "7461"

    @property
    def driver_name(self) -> str:
        return "AMD GPU (ROCm)"

    @property
    def command(self) -> str:
        return "amd-smi"

    def _is_os_supported(self) -> bool:
        """
        AMD ROCm drivers are supported on Ubuntu 22.04 and 24.04.
        """
        if not isinstance(self.node.os, Ubuntu):
            return False

        version = self.node.os.information.version
        # Support Ubuntu 22.04 (Jammy) and 24.04 (Noble)
        return version >= "22.4.0"

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

    def _verify_gpu_device(self) -> bool:
        """
        Verify that the AMD GPU device (V710) is detected on the system.
        """
        result = self.node.execute(
            f"lspci -d 1002:{self.AMD_V710_DEVICE_ID}",
            sudo=True,
            shell=True,
        )

        if result.exit_code == 0 and self.AMD_V710_DEVICE_ID in result.stdout:
            self._log.debug(f"AMD GPU V710 device detected: {result.stdout.strip()}")
            return True

        self._log.warning(
            f"AMD GPU V710 device (1002:{self.AMD_V710_DEVICE_ID}) not detected"
        )
        return False

    def _add_user_to_groups(self) -> None:
        """
        Add current user to render and video groups for GPU access.
        """
        username = self.node.tools[Whoami].get_username()

        result = self.node.execute(
            f"usermod -a -G render,video {username}",
            sudo=True,
        )
        if result.exit_code == 0:
            self._log.debug("Added user to render and video groups")

    def _install_driver(self) -> None:
        """
        Install AMD GPU (ROCm) driver on Ubuntu.
        """
        # Add user to required groups
        self._add_user_to_groups()

        # Determine Ubuntu codename
        os_info = self.node.os.information
        if os_info.version >= "24.4.0":
            codename = "noble"  # Ubuntu 24.04
        elif os_info.version >= "22.4.0":
            codename = "jammy"  # Ubuntu 22.04
        else:
            raise SkippedException(
                f"Ubuntu {os_info.version} is not supported. "
                f"Only Ubuntu 22.04 and 24.04 are supported."
            )

        self._log.info(f"Installing AMD GPU driver for Ubuntu {codename}")

        # Download amdgpu-install package
        installer_url = (
            f"https://repo.radeon.com/amdgpu-install/{self.ROCM_VERSION}/"
            f"ubuntu/{codename}/amdgpu-install_{self.ROCM_VERSION}."
            f"{self.ROCM_BUILD}-1_all.deb"
        )

        self._log.debug(f"Downloading AMD GPU installer from {installer_url}")
        wget_tool = self.node.tools[Wget]
        installer_path = wget_tool.get(
            installer_url,
            str(self.node.working_path),
            f"amdgpu-install_{self.ROCM_VERSION}.{self.ROCM_BUILD}-1_all.deb",
        )

        # Install the amdgpu-install package
        self._log.debug("Installing amdgpu-install package")
        assert isinstance(self.node.os, Posix), "AMD GPU installation requires Posix OS"

        result = self.node.execute(
            f"apt install -y {installer_path}",
            sudo=True,
            timeout=300,
        )
        result.assert_exit_code(
            0,
            f"Failed to install amdgpu-install package! "
            f"exit-code: {result.exit_code} stderr: {result.stderr}",
        )

        # Update package lists
        self.node.execute("apt update", sudo=True, timeout=300)

        # Install amdgpu-dkms and rocm
        self._log.info(
            "Installing amdgpu-dkms and rocm (this may take several minutes)"
        )
        result = self.node.execute(
            "apt install -y amdgpu-dkms rocm",
            sudo=True,
            timeout=1800,  # Can take up to 30 minutes
        )
        result.assert_exit_code(
            0,
            f"Failed to install amdgpu-dkms and rocm! "
            f"exit-code: {result.exit_code} stderr: {result.stderr}",
        )

        # Load the amdgpu module
        self._log.debug("Loading amdgpu kernel module")
        result = self.node.execute("modprobe amdgpu", sudo=True)
        if result.exit_code != 0:
            self._log.warning(f"Failed to load amdgpu module: {result.stderr}")

        # Verify installation with dmesg
        result = self.node.execute("dmesg | grep amdgpu", sudo=True, shell=True)
        if result.exit_code == 0:
            self._log.debug(f"amdgpu driver loaded: {result.stdout[:200]}")

        self._log.info("Successfully installed AMD GPU (ROCm) driver")

    def verify_installation(self) -> bool:
        """
        Verify AMD GPU driver installation using amd-smi monitor command.
        """
        result = self.node.execute("amd-smi monitor", sudo=True, timeout=30)
        if result.exit_code == 0:
            self._log.info(f"AMD GPU driver verified: {result.stdout[:200]}")
            return True

        self._log.warning(f"AMD GPU driver verification failed: {result.stderr}")
        return False
