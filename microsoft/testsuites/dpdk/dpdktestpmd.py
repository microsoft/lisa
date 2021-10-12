# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from pathlib import PurePath
from typing import List, Type

from assertpy import assert_that

from lisa.executable import Tool
from lisa.nic import NicInfo
from lisa.operating_system import CentOs, Redhat, Ubuntu
from lisa.tools import Echo, Git, Lspci, Wget
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
        self._last_run_output = ""
        result = self.node.execute("which dpdk-testpmd")
        if result.exit_code == 0:  # tools are already installed
            return True
        if self._install_dependencies():
            node = self.node
            git_tool = node.tools[Git]
            echo_tool = node.tools[Echo]
            self.dpdk_cwd = git_tool.clone(self._dpdk_github, cwd=node.working_path)
            dpdk_path = self.node.working_path.joinpath("dpdk")
            self.__execute_assert_zero("meson build", dpdk_path)
            dpdk_build_path = dpdk_path.joinpath("build")
            self.__execute_assert_zero("which ninja", dpdk_build_path)
            self.__execute_assert_zero("ninja", dpdk_build_path, timeout=1200)
            self.__execute_assert_zero("ninja install", dpdk_build_path)
            self.__execute_assert_zero("ldconfig", dpdk_build_path)
            library_bashrc_lines = [
                "export PKG_CONFIG_PATH=${PKG_CONFIG_PATH}:/usr/local/lib64/pkgconfig/",
                "export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/usr/local/lib64/",
            ]
            echo_tool.write_to_file(
                ";".join(library_bashrc_lines),
                "~/.bashrc",
                append=True,
            )
            return True
        else:
            return False

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
                    f"dracut --add-drivers '{mellanox_drivers} ib_uverbs' -f", cwd
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
            f"modprobe -a ib_uverbs rdma_ucm ib_umad ib_ipoib {mellanox_drivers}",
            cwd,
        )
        return True

    def generate_testpmd_include(self, node_nic: NicInfo, vdev_id: int) -> str:
        assert_that(node_nic.has_lower).is_true().described_as(
            (
                f"This interface {node_nic.upper} does not have a lower interface "
                "and pci slot associated with it. Aborting."
            )
        )
        return (
            f'--vdev="net_vdev_netvsc{vdev_id},iface={node_nic.upper}"'
            f' --allow "{node_nic.pci_slot}"'
        )

    def generate_testpmd_command(
        self, nic_to_include: NicInfo, vdev_id: int, mode: str, extra_args: str = ""
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
        nic_include_info = self.generate_testpmd_include(nic_to_include, vdev_id)
        return (
            f"{self._testpmd_install_path} -l 0-1 -n 4 --proc-type=primary "
            f"{nic_include_info} -- --forward-mode={mode} {extra_args} "
            "-a --stats-period 1"
        )

    def run_for_n_seconds(self, cmd: str, timeout: int) -> str:
        self._last_run_timeout = timeout
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
        self._last_run_output = proc_result.stdout
        return proc_result.stdout

    TX_PPS_KEY = "transmit-packets-per-second"
    RX_PPS_KEY = "receive-packets-per-second"

    testpmd_output_regex = {
        TX_PPS_KEY: r"Tx-pps:\s+([0-9]+)",
        RX_PPS_KEY: r"Rx-pps:\s+([0-9]+)",
    }

    def get_from_testpmd_output(self, search_key_constant: str) -> int:
        assert_that(self._last_run_output).described_as(
            "Could not find output from last testpmd run."
        ).is_not_equal_to("")
        matches = re.findall(
            self.testpmd_output_regex[search_key_constant], self._last_run_output
        )
        remove_zeros = [x for x in map(int, matches) if x != 0]
        assert_that(len(remove_zeros)).described_as(
            (
                "Could not locate any performance data spew from "
                f"this testpmd run. ({self.testpmd_output_regex[search_key_constant]}"
                " was not found in output)."
            )
        ).is_greater_than(0)
        total = sum(remove_zeros)
        return total // len(remove_zeros)

    def get_rx_pps(self) -> int:
        return self.get_from_testpmd_output(self.RX_PPS_KEY)

    def get_tx_pps(self) -> int:
        return self.get_from_testpmd_output(self.TX_PPS_KEY)
