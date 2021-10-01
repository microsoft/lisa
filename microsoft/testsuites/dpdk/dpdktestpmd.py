# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from pathlib import PurePath
from typing import List, Type
import time
from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import CentOs, Redhat, Ubuntu
from lisa.tools import Git, Lspci, Wget
from lisa.util import SkippedException


class DpdkTestpmd(Tool):
    # TestPMD tool to bundle the DPDK build and toolset together.

    @property
    def command(self) -> str:
        return self._testpmd_install_path

    _testpmd_install_path = "/usr/local/bin/dpdk-testpmd"
    _ubuntu_packages_1804 = [
        "librdmacm-dev",
        "build-essential",
        "libmnl-dev",
        "libelf-dev",
        "meson",
        "rdma-core",
        "librdmacm1",
        "libnuma-dev",
        "dpkg-dev",
        "pkg-config",
        "python3-pip",
        "python3-pyelftools",
        "python-pyelftools",
    ]

    _ubuntu_packages_2004 = [
        "build-essential",
        "librdmacm-dev",
        "libnuma-dev",
        "libmnl-dev",
        "librdmacm1",
        "meson",
        "ninja-build",
        "python3-pyelftools",
        "libelf-dev",
        "rdma-core",
    ]

    _redhat_packages = [
        "gcc",
        "make",
        "git",
        "tar",
        "wget",
        "dos2unix",
        "psmisc",
        "kernel-devel",
        "numactl-devel.x86_64",
        "librdmacm-devel",
        "pkgconfig",
        "libmnl-devel",
        "elfutils-libelf-devel",
        "python3-pip",
        "lspci",
        "libbpf-devel",
        "kernel-modules-extra",
        "kernel-headers",
    ]
    _rte_target = "x86_64-native-linuxapp-gcc"
    _dpdk_github = "https://github.com/DPDK/dpdk.git"
    _ninja_url = (
        "https://github.com/ninja-build/ninja/releases/"
        "download/v1.10.2/ninja-linux.zip"
    )

    def __execute_assert_zero(
        self, cmd: str, path: PurePath, timeout: int = 600
    ) -> str:
        result = self.node.execute(
            cmd, sudo=True, shell=True, cwd=path, timeout=timeout
        )
        assert_that(result.exit_code).is_zero()
        return result.stdout

    @property
    def can_install(self) -> bool:
        for _os in [Ubuntu, CentOs, Redhat]:
            if isinstance(self.node, _os):
                return True
        return False

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Wget]

    def _install(self) -> bool:
        result = self.node.execute("which dpdk-testpmd")
        if result.exit_code == 0:  # tools are already installed
            return True
        if self._install_dependencies():
            node = self.node
            git_tool = node.tools[Git]
            git_tool.clone(self._dpdk_github, cwd=node.working_path)
            dpdk_path = self.node.working_path.joinpath("dpdk")
            self.__execute_assert_zero("meson build", dpdk_path)
            dpdk_build_path = dpdk_path.joinpath("build")
            self.__execute_assert_zero("which ninja", dpdk_build_path)
            self.__execute_assert_zero("ninja", dpdk_build_path, timeout=1200)
            self.__execute_assert_zero("ninja install", dpdk_build_path)
            self.__execute_assert_zero("ldconfig", dpdk_build_path)
            return True
        else:
            return False

    def _reconfigure_forwarding(
        self, src_ip_addr: str, dst_ip_addr: str, dst_mac_addr: str
    ) -> None:
        result = self.node.execute("which dpdk-testpmd")
        result.assert_exit_code()  # ensure tools are already installed
        file_content = ""

        # prepare new macfwd.c from template c file
        filedir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(filedir, "macfwd_template.c"), "r") as macfwd_file:
            file_content = macfwd_file.read()
            src_ip_addr_array = src_ip_addr.replace(".", ",")
            dst_ip_addr_array = dst_ip_addr.replace(".", ",")
            dst_mac_addr_array = ["0x" + x for x in dst_mac_addr.split(":")]
            file_content = file_content.replace(
                "DST_IP_ADDRESS_REPLACEMENT_STR", dst_ip_addr_array
            )
            file_content = file_content.replace(
                "SRC_IP_ADDRESS_REPLACEMENT_STR", src_ip_addr_array
            )
            file_content = file_content.replace(
                "MAC_ADDRESS_REPLACEMENT_STRING", ",".join(dst_mac_addr_array)
            )
        tmpfile = os.path.join(filedir, "macfwd.c")
        with open(tmpfile, "w") as file_to_copy:
            file_to_copy.write(file_content)

        # locate the dir and copy the new macfwd.c file
        dpdk_path = self.node.working_path.joinpath("dpdk")
        dpdk_build_path = dpdk_path.joinpath("build")
        dst = dpdk_path.joinpath("app").joinpath("test-pmd").joinpath("macfwd.c")
        self.node.shell.copy(PurePath(tmpfile), dst)

        # remove the local tmpfile and rebuild dpdk
        # os.remove(tmpfile)
        self.__execute_assert_zero("ninja", dpdk_build_path, timeout=1200)
        self.__execute_assert_zero("ninja install", dpdk_build_path)
        self.__execute_assert_zero("ldconfig", dpdk_build_path)

    def _install_dependencies(self) -> bool:
        node = self.node
        cwd = node.working_path
        lspci = node.tools[Lspci]
        device_list = lspci.get_device_list()
        self.is_connect_x3 = any(
            ["ConnectX-3" in dev.device_info for dev in device_list]
        )
        if self.is_connect_x3:
            mellanox_drivers = "mlx4_core mlx4_ib"
        else:
            mellanox_drivers = "mlx5_core mlx5_ib"
        if isinstance(node.os, Ubuntu):
            # TODO: Workaround for type checker below
            if "18.04" in node.os.information.release:
                node.os.install_packages(list(self._ubuntu_packages_1804))
                self.__execute_assert_zero("pip3 install --upgrade meson", cwd)
                self.__execute_assert_zero("mv /usr/bin/meson /usr/bin/meson.bak", cwd)
                self.__execute_assert_zero(
                    "ln -s /usr/local/bin/meson /usr/bin/meson", cwd
                )
                self.__execute_assert_zero("pip3 install --upgrade ninja", cwd)
            elif "20.04" in node.os.information.release:
                node.os.install_packages(list(self._ubuntu_packages_2004))
            self.__execute_assert_zero(
                "modprobe -a rdma_cm rdma_ucm ib_core ib_uverbs",
                cwd,
            )

        elif isinstance(node.os, Redhat):
            self.__execute_assert_zero(
                "yum update -y --disablerepo='*' --enablerepo='*microsoft*'", cwd
            )
            node.os.group_install_packages("Development Tools")
            node.os.group_install_packages("Infiniband Support")
            # TODO: Workaround for type checker below
            node.os.install_packages(list(self._redhat_packages))

            if not self.is_connect_x3:
                self.__execute_assert_zero(
                    "dracut --add-drivers 'mlx5_ib ib_uverbs' -f", cwd
                )
            self.__execute_assert_zero(
                "modprobe -a ib_core ib_uverbs mlx4_en mlx4_core mlx5_core mlx4_ib"
                + " mlx5_ib",
                cwd,
            )  # add mellanox drivers
            self.__execute_assert_zero("systemctl enable rdma", cwd)
            self.__execute_assert_zero("pip3 install --upgrade meson", cwd)
            self.__execute_assert_zero("ln -s /usr/local/bin/meson /usr/bin/meson", cwd)

            wget_tool = self.node.tools[Wget]
            wget_tool.get(self._ninja_url)
            node.execute(f"mv ninja-linux.zip {node.working_path}/")
            self.__execute_assert_zero(
                "unzip ninja-linux.zip && mv ninja /usr/bin/ninja", cwd
            )
            self.__execute_assert_zero("pip3 install --upgrade pyelftools", cwd)
        else:
            raise SkippedException(
                f"This os {node.os} is not implemented by the DPDK suite."
            )
        self.__execute_assert_zero(
            f"modprobe -a uio ib_uverbs rdma_ucm ib_umad ib_ipoib {mellanox_drivers}",
            cwd,
        )
        return True

    def _generate_testpmd_command(
        self, nic_to_include: str, mode: str, extra_args: str = ""
    ) -> str:
        #   testpmd \
        #   -l <core-list> \
        #   -n <num of mem channels> \
        #   -w <pci address of the device you plan to use> \
        #   --vdev="net_vdev_netvsc<id>,iface=<the iface to attach to>" \
        #   -- --port-topology=chained \
        #   --nb-cores <number of cores to use for test pmd> \
        #   --forward-mode=txonly \
        #   --eth-peer=<port id>,<receiver peer MAC address> \
        #   --stats-period <display interval in seconds>
        return (
            f"{self._testpmd_install_path} -l 0-1 -n 4 --proc-type=primary "
            f"{nic_to_include} -- --forward-mode={mode} {extra_args} -a --stats-period 1"
        )

    def run_for_n_seconds(self, cmd: str, timeout: int) -> str:
        self.node.log.info(f"{self.node.name} running: {cmd}")
        timer_proc = self.node.execute_async(
            f"sleep {timeout} && killall -s INT {cmd.split()[0]}",
            sudo=True,
            shell=True,
        )
        testpmd_proc = self.node.execute_async(
            cmd,
            sudo=True,
        )
        time.sleep(timeout)
        timer_proc.wait_result()
        proc_result = testpmd_proc.wait_result()
        return proc_result.stdout
