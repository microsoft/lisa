# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from assertpy import assert_that

from lisa.base_tools import Cat, Sed, Uname, Wget
from lisa.feature import Feature
from lisa.operating_system import CentOs, Redhat, Ubuntu
from lisa.tools import Firewall, Make
from lisa.tools.service import Service
from lisa.tools.tar import Tar
from lisa.util import LisaException

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

    def get_ib_interfaces(self) -> List[IBDevice]:
        """Gets the list of Infiniband devices
        excluding any ethernet devices
        and get their corresponding network interface
        Returns list of IBDevice(ib_device_name, nic_name, ip_addr)
        Example IBDevice("mlx5_ib0", "ib0", "172.16.1.23")"""
        ib_devices = []
        device_info = self._get_ib_device_info()
        for device in device_info:
            if device["link_layer"].strip() == "InfiniBand" and "node_guid" in device:
                device_name = device["hca_id"].strip()
                guid = device["node_guid"].strip()
                # Get the last three bytes of guid
                # Example
                # guid = 0015:5dff:fe33:ff0c
                # mpat = 33:ff:0c (This will match the ib device)
                mpat = f"{guid[12:17]}:{guid[17:19]}"
                for (nic_name, nic_info) in self._node.nics.nics.items():
                    result = self._node.execute(f"/sbin/ip addr show {nic_name}")
                    if mpat in result.stdout and "ib" in nic_name:
                        assert_that(nic_info.ip_addr).described_as(
                            f"NIC {nic_name} does not have an ip address."
                        ).is_not_empty()
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

    def get_pkey(self) -> str:
        ib_device_name = self.get_ib_interfaces()[0].ib_device_name
        cat = self._node.tools[Cat]
        return cat.read(f"/sys/class/infiniband/{ib_device_name}/ports/1/pkeys/0")

    def setup_rdma(self) -> None:
        node = self._node
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
            "python-dev",
            "python-setuptools",
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
            "python-setuptools",
            "g++",
            "libc6-i386",
            "lib32gcc-8-dev",
        ]
        redhat_required_packages = [
            "git",
            "zip",
            "python3",
            "kernel-rpm-macros",
            "gdb-headless",
            "python36-devel",
            "elfutils-libelf-devel",
            "rpm-build",
            "make",
            "gcc",
            "tcl",
            "tk",
            "gcc-gfortran",
            "tcsh",
            "kernel-devel",
            "kernel-modules-extra",
            "createrepo",
            "libtool",
            "fuse-libs",
            "gcc-c++",
            "glibc.i686",
            "libgcc.i686",
            "byacc",
            "libevent",
        ]
        if isinstance(node.os, CentOs):
            node.execute(
                "yum install -y https://partnerpipelineshare.blob.core.windows.net"
                f"/kernel-devel-rpms/kernel-devel-{kernel}.rpm",
                sudo=True,
            )

        if isinstance(node.os, Redhat):
            if node.os.information.version.major == 7:
                redhat_required_packages.append("python-devel")
            else:
                redhat_required_packages.append("python3-devel")
                redhat_required_packages.append("python2-devel")
            node.os.install_packages(list(redhat_required_packages))
        elif isinstance(node.os, Ubuntu):
            node.os.install_packages(list(ubuntu_required_packages))
        else:
            raise LisaException(f"Unsupported distro: {node.os.name} is not supported.")

        # Turn off firewall
        firewall = node.tools[Firewall]
        firewall.stop()

        # Disable SELinux
        sed = node.tools[Sed]
        sed.substitute(
            regexp="SELINUX=enforcing",
            replacement="SELINUX=disabled",
            file="/etc/selinux/config",
            sudo=True,
        )

        # Install OFED
        mofed_version = "5.4-3.0.3.0"
        if isinstance(node.os, Redhat):
            os_class = "rhel"
        else:
            os_class = node.os.name.lower()

        os_version = node.os.information.release.split(".")
        mofed_folder = (
            f"MLNX_OFED_LINUX-{mofed_version}-{os_class}"
            f"{os_version[0]}."
            f"{os_version[1]}-x86_64"
        )
        tarball_name = f"{mofed_folder}.tgz"
        mlnx_ofed_download_url = (
            f"https://partnerpipelineshare.blob.core.windows.net/ofed/{tarball_name}"
        )

        wget = node.tools[Wget]
        wget.get(url=mlnx_ofed_download_url, file_path=".", filename=tarball_name)
        tar = node.tools[Tar]
        tar.extract(file=tarball_name, dest_dir=".", gzip=True)

        extra_params = ""
        if isinstance(node.os, Redhat):
            extra_params = (
                f"--kernel {kernel} --kernel-sources /usr/src/kernels/{kernel}  "
                f"--skip-repo --skip-unsupported-devices-check --without-fw-update"
            )
        node.execute(
            f"./{mofed_folder}/mlnxofedinstall --add-kernel-support {extra_params}",
            expected_exit_code=0,
            expected_exit_code_failure_message="SetupRDMA: failed to install "
            "MOFED Drivers",
            sudo=True,
        )
        node.execute(
            "/etc/init.d/openibd force-restart",
            expected_exit_code=0,
            expected_exit_code_failure_message="SetupRDMA: failed to restart driver",
            sudo=True,
        )

        # Update waagent.conf
        sed.substitute(
            regexp="# OS.EnableRDMA=y",
            replacement="OS.EnableRDMA=y",
            file="/etc/waagent.conf",
            sudo=True,
        )
        sed.substitute(
            regexp="# AutoUpdate.Enabled=y",
            replacement="AutoUpdate.Enabled=y",
            file="/etc/waagent.conf",
            sudo=True,
        )

        service = node.tools[Service]
        if isinstance(node.os, Ubuntu):
            service.restart_service("walinuxagent")
        else:
            service.restart_service("waagent")

    def install_intel_mpi(self) -> None:
        node = self._node
        # Install Intel MPI
        wget = node.tools[Wget]
        script_path = wget.get(
            "https://partnerpipelineshare.blob.core.windows.net/mpi/"
            "l_mpi_oneapi_p_2021.1.1.76_offline.sh",
            executable=True,
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
        tar_file_path = wget.get(
            "https://download.open-mpi.org/release/open-mpi/v4.0/openmpi-4.0.5.tar.gz",
            executable=True,
        )
        tar = node.tools[Tar]
        tar.extract(tar_file_path, ".", gzip=True)
        openmpi_folder = node.get_pure_path("./openmpi-4.0.5")

        node.execute(
            "./configure --enable-mpirun-prefix-by-default",
            shell=True,
            cwd=openmpi_folder,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to configure Open MPI",
        )

        make = node.tools[Make]
        make.make("", cwd=openmpi_folder)
        make.make_install(cwd=openmpi_folder)

    def install_ibm_mpi(self) -> None:
        node = self._node
        # Install Open MPI
        wget = node.tools[Wget]
        script_path = wget.get(
            "https://partnerpipelineshare.blob.core.windows.net/mpi/"
            "platform_mpi-09.01.04.03r-ce.bin",
            executable=True,
        )
        node.execute(
            f"{script_path} -i silent",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to install IBM MPI.",
        )
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
            "https://partnerpipelineshare.blob.core.windows.net/"
            "mpi/mvapich2-2.3.2.tar.gz"
        )
        tar = node.tools[Tar]
        tar.extract(tar_file_path, ".", gzip=True)
        mvapichmpi_folder = node.get_pure_path("./mvapich2-2.3.2")

        if isinstance(node.os, Ubuntu):
            params = "--disable-fortran --disable-mcast"
        else:
            params = ""
        node.execute(
            f"./configure {params}",
            shell=True,
            cwd=mvapichmpi_folder,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to configure MVAPICH MPI",
        )
        make = node.tools[Make]
        make.make("", cwd=mvapichmpi_folder)
        make.make_install(cwd=mvapichmpi_folder)
