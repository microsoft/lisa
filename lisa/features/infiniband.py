# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from assertpy import assert_that
from retry import retry

from lisa.base_tools import Cat, Sed, Uname, Wget
from lisa.feature import Feature
from lisa.features import Disk
from lisa.operating_system import CBLMariner, CpuArchitecture, Oracle, Redhat, Ubuntu
from lisa.tools import Firewall, Ls, Lscpu, Lspci, Make, Service
from lisa.tools.tar import Tar
from lisa.util import (
    LisaException,
    MissingPackagesException,
    UnsupportedDistroException,
    UnsupportedKernelException,
)

FEATURE_NAME_INFINIBAND = "Infiniband"


@dataclass
class IBDevice:
    ib_device_name: str
    nic_name: str
    ip_addr: str


class Infiniband(Feature):
    # Example output of ibv_devinfo:
    # hca_id: mlx5_0
    #     transport:                      InfiniBand (0)
    #     fw_ver:                         16.28.4000
    #     node_guid:                      0015:5dff:fe33:ff0c
    #     sys_image_guid:                 0c42:a103:0065:bafe
    #     vendor_id:                      0x02c9
    #     vendor_part_id:                 4120
    #     hw_ver:                         0x0
    #     board_id:                       MT_0000000010
    #     phys_port_cnt:                  1
    #             port:   1
    #                     state:                  PORT_ACTIVE (4)
    #                     max_mtu:                4096 (5)
    #                     active_mtu:             4096 (5)
    #                     sm_lid:                 55
    #                     port_lid:               693
    #                     port_lmc:               0x00
    #                     link_layer:             InfiniBand
    _ib_info_pattern = re.compile(r"(\s*(?P<id>\S*):\s*(?P<value>.*)\n?)")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self.is_hpc_image = False
        self.resource_disk_path = self._node.features[
            Disk
        ].get_resource_disk_mount_point()
        self.setup_rdma()

    def enabled(self) -> bool:
        return True

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_INFINIBAND

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def is_over_sriov(self) -> bool:
        raise NotImplementedError

    # nd stands for network direct
    # example SKU: Standard_H16mr
    def is_over_nd(self) -> bool:
        raise NotImplementedError

    def _is_legacy_device(self) -> bool:
        lspci = self._node.tools[Lspci]
        device_list = lspci.get_devices()
        return any("ConnectX-3" in device.device_info for device in device_list)

    @retry(tries=10, delay=5)  # type: ignore
    def get_ib_interfaces(self) -> List[IBDevice]:
        """Gets the list of Infiniband devices
        excluding any ethernet devices
        and get their corresponding network interface
        Returns list of IBDevice(ib_device_name, nic_name, ip_addr)
        Example IBDevice("mlx5_ib0", "ib0", "172.16.1.23")"""
        ib_devices = []
        device_info = self._get_ib_device_info()
        self._node.nics.reload()
        for device in device_info:
            if device["link_layer"].strip() == "InfiniBand" and "node_guid" in device:
                device_name = device["hca_id"].strip()
                guid = device["node_guid"].strip()
                # Get the last three bytes of guid
                # Example
                # guid = 0015:5dff:fe33:ff0c
                # mpat = 33:ff:0c (This will match the ib device)
                mpat = f"{guid[12:17]}:{guid[17:19]}"
                for nic_name, nic_info in self._node.nics.nics.items():
                    result = self._node.execute(f"/sbin/ip addr show {nic_name}")
                    if mpat in result.stdout and "ib" in nic_name:
                        assert_that(nic_info.ip_addr).described_as(
                            f"NIC {nic_name} does not have an ip address."
                        ).is_not_none()
                        ib_devices.append(
                            IBDevice(device_name, nic_name, nic_info.ip_addr)
                        )

        assert_that(ib_devices).described_as(
            "Failed to get any InfiniBand device / interface pairs"
        ).is_not_empty()
        return ib_devices

    def _get_ib_device_info(self) -> List[Dict[str, str]]:
        device_info = []
        devices = self._get_ib_device_names()
        for device_name in devices:
            result = self._node.execute(
                f"ibv_devinfo -d {device_name}",
                expected_exit_code=0,
                expected_exit_code_failure_message="Failed to get device info from "
                f"ibv_devinfo for infiniband device {device_name}",
            )
            d = {
                match.group("id"): match.group("value")
                for match in self._ib_info_pattern.finditer(result.stdout)
            }
            if "hca_id" in d:
                device_info.append(d)

        assert_that(device_info).described_as(
            "Failed to get device info for any InfiniBand devices"
        ).is_not_empty()
        return device_info

    def _get_ib_device_names(self) -> List[str]:
        node = self._node
        result = node.execute(
            "ls /sys/class/infiniband",
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to get InfiniBand"
            " devices from /sys/class/infiniband",
        )

        assert_that(result.stdout).described_as(
            "No infiniband devices found in /sys/class/infiniband"
        ).is_not_empty()
        return result.stdout.split()

    def _get_ofed_version(self) -> str:
        node = self._node
        default = "5.4-3.0.3.0"
        if self._is_legacy_device():
            return "4.9-5.1.0.0"
        if (
            isinstance(node.os, Ubuntu) and node.os.information.version >= "20.4.0"
        ) or (isinstance(node.os, Redhat) and node.os.information.version >= "8.2.0"):
            return "5.8-1.1.2.1"

        return default

    def get_pkey(self) -> str:
        ib_device_name = self.get_ib_interfaces()[0].ib_device_name
        cat = self._node.tools[Cat]
        return cat.read(f"/sys/class/infiniband/{ib_device_name}/ports/1/pkeys/0")

    def setup_rdma(self) -> None:
        if not self.is_hpc_image:
            self.install_ofed()

        node = self._node
        # Turn off firewall
        firewall = node.tools[Firewall]
        firewall.stop()
        # Disable SELinux
        if not isinstance(node.os, CBLMariner):
            sed = node.tools[Sed]
            sed.substitute(
                regexp="SELINUX=enforcing",
                replacement="SELINUX=disabled",
                file="/etc/selinux/config",
                sudo=True,
            )

        # for non-hpc images, add net.ifnames=0 biosdevname=0 in boot kernel parameter
        # to make ib device name consistent across reboots
        if (
            not node.tools[Service].is_service_running("azure_persistent_rdma_naming")
            and isinstance(node.os, Ubuntu)
            and node.os.information.version > "18.4.0"
        ):
            node.tools[Sed].substitute(
                regexp='GRUB_CMDLINE_LINUX="\\(.*\\)"',
                replacement='GRUB_CMDLINE_LINUX="\\1 net.ifnames=0 biosdevname=0"',
                file="/etc/default/grub",
                sudo=True,
            )
            node.execute("update-grub", sudo=True)
            node.reboot()

    def _install_dependencies(self) -> None:
        node = self._node
        os_version = node.os.information.release.split(".")
        lscpu = node.tools[Lscpu]
        arch = lscpu.get_architecture()
        # Dependencies
        kernel = node.tools[Uname].get_linux_information().kernel_version_raw
        ubuntu_required_packages = [
            "build-essential",
            "numactl",
            "rpm",
            "libnuma-dev",
            "libmpc-dev",
            "libmpfr-dev",
            "libxml2-dev",
            "m4",
            "byacc",
            "python3-setuptools",
            "tcl",
            "environment-modules",
            "tk",
            "texinfo",
            "libudev-dev",
            "binutils",
            "binutils-dev",
            "selinux-policy-dev",
            "flex",
            "libnl-3-dev",
            "libnl-route-3-dev",
            "libnl-3-200",
            "bison",
            "libnl-route-3-200",
            "gfortran",
            "cmake",
            "libnl-3-dev",
            "libnl-route-3-dev",
            "libsecret-1-0",
            "dkms",
            "python3-setuptools",
            "g++",
            "cloud-init",
            "walinuxagent",
            "net-tools",
        ]
        if arch == CpuArchitecture.ARM64:
            ubuntu_required_packages.append("libc6-armhf-cross")
        else:
            ubuntu_required_packages.append("libc6-i386")
        redhat_required_packages = [
            "gtk2",
            "atk",
            "cairo",
            "git",
            "zip",
            "python3",
            "kernel-rpm-macros",
            "gdb-headless",
            "elfutils-libelf-devel",
            "rpm-build",
            "make",
            "gcc",
            "tcl",
            "tk",
            "gcc-gfortran",
            "tcsh",
            "kernel-modules-extra",
            "createrepo",
            "libtool",
            "fuse-libs",
            "gcc-c++",
            "glibc",
            "libgcc",
            "byacc",
            "libevent",
            "pciutils",
            "lsof",
        ]
        cblmariner_required_packages = [
            "rdma-core",
            "rdma-core-devel",
            "libibverbs",
            "libibverbs-utils",
            "build-essential",
            "ucx",
            "ucx-ib",
            "ucx-rdmacm",
            "ucx-cma",
        ]

        if isinstance(node.os, Redhat):
            if node.os.information.version.major >= 9:
                redhat_required_packages.append("perl-CPAN")
                redhat_required_packages.append("perl-Pod-Html")
            for package in [
                "python36-devel",
                "python3-devel",
                "python-devel",
                "python2-devel",
            ]:
                if node.os.is_package_in_repo(package):
                    redhat_required_packages.append(package)
            node.os.install_packages(redhat_required_packages)
            # enable olX_UEKRY repo when it is uek kernel
            # then install uek kernel source code
            if isinstance(node.os, Oracle) and "uek" in kernel:
                node.execute(
                    "yum-config-manager --enable "
                    f"ol{os_version[0]}_UEKR{os_version[1]}",
                    sudo=True,
                )
                node.os.install_packages("kernel-uek-devel-$(uname -r)")
            else:
                try:
                    node.os.install_packages("kernel-devel-$(uname -r)")
                except MissingPackagesException:
                    node.log.debug(
                        "kernel-devel-$(uname -r) not found. Trying kernel-devel"
                    )
                    node.os.install_packages("kernel-devel")
        elif isinstance(node.os, Ubuntu) and node.os.information.version >= "18.4.0":
            check_package = [
                "python3-dev",
                "python-dev",
            ]
            if arch == CpuArchitecture.ARM64:
                check_package.append("libgcc-9-dev")
                check_package.append("libgcc-8-dev")
            else:
                check_package.append("lib32gcc-9-dev")
                check_package.append("lib32gcc-8-dev")
            for package in check_package:
                if node.os.is_package_in_repo(package):
                    ubuntu_required_packages.append(package)
            node.os.install_packages(ubuntu_required_packages)
        elif isinstance(node.os, CBLMariner):
            node.os.install_packages(cblmariner_required_packages)
        else:
            raise UnsupportedDistroException(
                node.os,
                "Only CentOS 7.6-8.3, Ubuntu 18.04-22.04 distros are "
                "supported by the HPC team. Also supports CBLMariner 2.0 "
                "distro which uses the Mellanox inbox driver",
            )

    def install_ofed(self) -> None:
        node = self._node
        os_version = node.os.information.release.split(".")
        # Dependencies
        kernel = node.tools[Uname].get_linux_information().kernel_version_raw
        kernel_version = node.tools[Uname].get_linux_information().kernel_version
        self._install_dependencies()

        # CBLMariner uses the Mellanox inbox driver instead of the OFED driver
        if isinstance(node.os, CBLMariner):
            return

        # Install OFED
        ofed_version = self._get_ofed_version()
        if isinstance(node.os, Oracle):
            os_class = "ol"
        elif isinstance(node.os, Redhat):
            os_class = "rhel"
        else:
            os_class = node.os.name.lower()

        # refer https://forums.developer.nvidia.com/t/connectx-3-on-ubuntu-20-04/206201/8 # noqa: E501
        # for why we don't support ConnectX-3 on kernel >= 5.6
        if self._is_legacy_device() and kernel_version >= "5.6.0":
            raise UnsupportedKernelException(
                node.os,
                "OFED driver for ConnectX-3 devices is not supported on "
                "kernel versions >= 5.6",
            )

        ofed_folder = (
            f"MLNX_OFED_LINUX-{ofed_version}-{os_class}"
            f"{os_version[0]}."
            f"{os_version[1]}-x86_64"
        )
        tarball_name = f"{ofed_folder}.tgz"
        mlnx_ofed_download_url = (
            f"https://content.mellanox.com/ofed/MLNX_OFED-{ofed_version}"
            f"/{tarball_name}"
        )

        wget = node.tools[Wget]
        try:
            wget.get(
                url=mlnx_ofed_download_url,
                file_path=self.resource_disk_path,
                filename=tarball_name,
                overwrite=False,
                sudo=True,
            )
        except LisaException as e:
            if "404: Not Found." in str(e):
                raise UnsupportedDistroException(
                    node.os, f"{mlnx_ofed_download_url} doesn't exist."
                )
        tar = node.tools[Tar]
        tar.extract(
            file=f"{self.resource_disk_path}/{tarball_name}",
            dest_dir=self.resource_disk_path,
            gzip=True,
            sudo=True,
        )

        extra_params = ""
        if isinstance(node.os, Redhat):
            ls = node.tools[Ls]
            kernel_dirs = ls.list_dir("/usr/src/kernels")
            if f"/usr/src/kernels/{kernel}" in kernel_dirs:
                kernel_src = f"/usr/src/kernels/{kernel}"
            elif kernel_dirs:
                kernel_src = kernel_dirs[0]
            else:
                raise UnsupportedKernelException(
                    node.os,
                    "Cannot install OFED drivers without kernel-devel package",
                )

            extra_params = (
                f"--kernel {kernel} --kernel-sources {kernel_src}  "
                f"--skip-repo --without-fw-update"
            )

        if not self._is_legacy_device():
            extra_params += " --skip-unsupported-devices-check"

        try:
            node.execute(
                f"{self.resource_disk_path}/{ofed_folder}/mlnxofedinstall "
                f"--add-kernel-support {extra_params} "
                f"--tmpdir {self.resource_disk_path}/tmp",
                expected_exit_code=0,
                expected_exit_code_failure_message="SetupRDMA: failed to install "
                "OFED Drivers",
                sudo=True,
                timeout=1200,
            )
        except AssertionError as e:
            raise MissingPackagesException(["OFED Drivers"]) from e
        node.execute(
            "/etc/init.d/openibd force-restart",
            expected_exit_code=0,
            expected_exit_code_failure_message="SetupRDMA: failed to restart driver",
            sudo=True,
        )

    def install_intel_mpi(self) -> None:
        node = self._node
        # Install Intel MPI
        wget = node.tools[Wget]
        script_path = wget.get(
            "https://registrationcenter-download.intel.com/akdlm/IRC_NAS/17397/"
            "l_mpi_oneapi_p_2021.1.1.76_offline.sh",
            file_path=self.resource_disk_path,
            executable=True,
            overwrite=False,
            sudo=True,
        )
        node.execute(
            f"{script_path} -s -a -s --eula accept",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to install IntelMPI",
        )

    def install_open_mpi(self) -> None:
        node = self._node
        # Install Open MPI
        wget = node.tools[Wget]
        tar_file = (
            "https://download.open-mpi.org/release/open-mpi/v4.1/openmpi-4.1.5.tar.gz"
        )
        # tar_file => openmpi-4.1.5.tar.gz => openmpi-4.1.5
        file_name = tar_file.rsplit("/", maxsplit=1)[-1].rsplit(".", maxsplit=2)[0]
        tar_file_path = wget.get(
            tar_file,
            file_path=self.resource_disk_path,
            executable=True,
            overwrite=False,
            sudo=True,
        )
        tar = node.tools[Tar]
        tar.extract(tar_file_path, self.resource_disk_path, gzip=True, sudo=True)
        openmpi_folder = node.get_pure_path(f"{self.resource_disk_path}/{file_name}")

        node.execute(
            "./configure --enable-mpirun-prefix-by-default",
            sudo=True,
            shell=True,
            cwd=openmpi_folder,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to configure Open MPI",
        )

        make = node.tools[Make]
        make.make("", cwd=openmpi_folder, sudo=True)
        make.make_install(cwd=openmpi_folder, sudo=True)

    def install_ibm_mpi(self, platform_mpi_url: str) -> None:
        node = self._node
        if isinstance(node.os, Redhat):
            node.os.install_packages("libstdc++.i686")
        if isinstance(node.os, Ubuntu):
            for package in [
                "lib32gcc-9-dev",
                "python3-dev",
                "lib32gcc-8-dev",
                "python-dev",
            ]:
                if node.os.is_package_in_repo(package):
                    node.os.install_packages(package)
        # Install Open MPI
        wget = node.tools[Wget]
        script_path = wget.get(
            platform_mpi_url,
            file_path=self.resource_disk_path,
            executable=True,
            overwrite=False,
            sudo=True,
        )
        node.execute(
            f"{script_path} -i silent",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to install IBM MPI.",
        )
        # if it is hpc image, use module tool load mpi/hpcx to compile the ping_pong.c
        if self.is_hpc_image:
            node.execute(
                "bash -c 'source /usr/share/modules/init/bash"
                " && module load mpi/hpcx && mpicc -o ping_pong ping_pong.c'",
                cwd=node.get_pure_path("/opt/ibm/platform_mpi/help"),
                sudo=True,
                shell=True,
            )
        else:
            make = node.tools[Make]
            make.make(
                "",
                cwd=node.get_pure_path("/opt/ibm/platform_mpi/help"),
                update_envs={"MPI_IB_PKEY": self.get_pkey()},
                sudo=True,
            )

    def install_mvapich_mpi(self) -> None:
        node = self._node
        # Install Open MPI
        wget = node.tools[Wget]
        tar_file_path = wget.get(
            "https://mvapich.cse.ohio-state.edu/download/mvapich/"
            "mv2/mvapich2-2.3.7-1.tar.gz",
            file_path=self.resource_disk_path,
            overwrite=False,
            sudo=True,
        )
        tar = node.tools[Tar]
        tar.extract(tar_file_path, self.resource_disk_path, gzip=True, sudo=True)
        mvapichmpi_folder = node.get_pure_path(
            f"{self.resource_disk_path}/mvapich2-2.3.7-1"
        )

        if (
            isinstance(node.os, Ubuntu)
            or isinstance(node.os, CBLMariner)
            or (isinstance(node.os, Redhat) and node.os.information.version.major >= 9)
        ):
            params = "--disable-fortran --disable-mcast"
        else:
            params = ""
        node.execute(
            f"./configure {params}",
            shell=True,
            sudo=True,
            cwd=mvapichmpi_folder,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to configure MVAPICH MPI",
        )
        make = node.tools[Make]
        make.make("", cwd=mvapichmpi_folder, sudo=True)
        make.make_install(cwd=mvapichmpi_folder, sudo=True)
