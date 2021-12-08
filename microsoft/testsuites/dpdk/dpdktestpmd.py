# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePath
from typing import List, Pattern, Tuple, Type, Union

from assertpy import assert_that, fail
from semver import VersionInfo

from lisa.executable import Tool
from lisa.nic import NicInfo
from lisa.operating_system import CentOs, Redhat, Ubuntu
from lisa.tools import Echo, Git, Lspci, Modprobe, Tar, Wget
from lisa.util import LisaException, UnsupportedDistroException


class DpdkTestpmd(Tool):
    # TestPMD tool to bundle the DPDK build and toolset together.

    # regex to identify sriov re-enable event, example:
    # EAL: Probe PCI driver: net_mlx4 (15b3:1004) device: e8ef:00:02.0 (socket 0)
    _search_hotplug_regex = re.compile(
        (
            r"EAL: Probe PCI driver: ([a-z_A-Z0-9\-]+) "
            r"\([0-9a-fA-F]{4}:[0-9a-fA-F]{4}\) device: "
            r"[a-fA-F0-9]{4}:[a-fA-F0-9]{2}:"
            r"[a-fA-F0-9]{2}\.[a-fA-F0-9]"
            r" \(socket 0\)"
        )
    )

    # ex v19.11-rc3 or 19.11
    _version_info_from_git_tag_regex = re.compile(
        r"v?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)"
    )
    # ex dpdk-21.08.zip or dpdk-21.08-rc4.zip
    _version_info_from_tarball_regex = re.compile(
        r"dpdk-(?P<major>[0-9]+)\.(?P<minor>[0-9]+)"
    )

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
        "ibverbs-providers",
        "pkg-config",
    ]

    _redhat_packages = [
        "psmisc",
        "kernel-devel-$(uname -r)",
        "numactl-devel.x86_64",
        "librdmacm-devel",
        "pkgconfig",
        "libmnl-devel",
        "elfutils-libelf-devel",
        "python3-pip",
        "libbpf-devel",
        "kernel-modules-extra",
        "kernel-headers",
    ]
    _rte_target = "x86_64-native-linuxapp-gcc"
    _ninja_url = (
        "https://github.com/ninja-build/ninja/releases/"
        "download/v1.10.2/ninja-linux.zip"
    )

    def __execute_assert_zero(
        self, cmd: str, path: PurePath, timeout: int = 600
    ) -> str:
        result = self.node.execute(
            cmd,
            sudo=True,
            shell=True,
            cwd=path,
            timeout=timeout,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Command failed with nonzero error code during testpmd installation "
                f"in dir '{path.as_posix()}'"
            ),
        )
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

    def set_dpdk_source(self, dpdk_source: str) -> None:
        self._dpdk_source = dpdk_source

    def set_dpdk_branch(self, dpdk_branch: str) -> None:
        self._dpdk_branch = dpdk_branch

    def _determine_network_hardware(self) -> None:
        lspci = self.node.tools[Lspci]
        device_list = lspci.get_device_list()
        self.is_connect_x3 = any(
            ["ConnectX-3" in dev.device_info for dev in device_list]
        )

    def _install(self) -> bool:
        self._testpmd_output_after_reenable = ""
        self._testpmd_output_before_rescind = ""
        self._testpmd_output_during_rescind = ""
        self._last_run_output = ""
        self._dpdk_version_info: Union[VersionInfo, None] = None
        self._determine_network_hardware()
        node = self.node

        # installing from distro package manager
        if self._dpdk_source and self._dpdk_source == "package_manager":
            self.node.log.info(
                "Installing dpdk and dev package from package manager..."
            )
            if isinstance(node.os, Ubuntu):
                node.os.install_packages(["dpdk", "dpdk-dev"])
            elif isinstance(node.os, Redhat):
                node.os.install_packages(["dpdk", "dpdk-devel"])
            else:
                raise NotImplementedError(
                    "Dpdk package names are missing in dpdktestpmd.install"
                    f" for os {node.os.name}"
                )

            self._dpdk_version_info = node.os.get_package_information("dpdk")

            if self._dpdk_version_info >= "19.11.0":
                self._testpmd_install_path = "dpdk-testpmd"
            else:
                self._testpmd_install_path = "testpmd"
            self._load_drivers_for_dpdk()
            return True

        # otherwise install from source tarball or git
        self.node.log.info(f"Installing dpdk from source: {self._dpdk_source}")
        self._dpdk_repo_path_name = "dpdk"
        result = self.node.execute("which dpdk-testpmd")
        self.dpdk_path = self.node.working_path.joinpath(self._dpdk_repo_path_name)
        if result.exit_code == 0:  # tools are already installed
            return True
        self._install_dependencies()
        git_tool = node.tools[Git]
        echo_tool = node.tools[Echo]

        if self._dpdk_source and self._dpdk_source.endswith(".tar.gz"):
            wget_tool = node.tools[Wget]
            tar_tool = node.tools[Tar]
            if self._dpdk_branch:
                node.log.warn(
                    (
                        "DPDK tarball source does not need dpdk_branch defined. "
                        "User-defined variable dpdk_branch will be ignored."
                    )
                )
            working_path = str(node.working_path)
            wget_tool.get(
                self._dpdk_source,
                working_path,
            )
            dpdk_filename = self._dpdk_source.split("/")[-1]
            # extract tar into dpdk/ folder and discard old root folder name
            tar_tool.extract(
                str(node.working_path.joinpath(dpdk_filename)),
                str(self.dpdk_path),
                strip_components=1,
            )
            self.set_version_info_from_source_install(
                self._dpdk_source, self._version_info_from_tarball_regex
            )
        else:
            git_tool.clone(
                self._dpdk_source,
                cwd=node.working_path,
                dir_name=self._dpdk_repo_path_name,
            )
            if self._dpdk_branch:
                git_tool.checkout(self._dpdk_branch, cwd=self.dpdk_path)
                self.set_version_info_from_source_install(
                    self._dpdk_branch, self._version_info_from_git_tag_regex
                )
        self._load_drivers_for_dpdk()
        self.__execute_assert_zero("meson build", self.dpdk_path)
        dpdk_build_path = self.dpdk_path.joinpath("build")
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
            node.get_pure_path("~/.bashrc"),
            append=True,
        )

        return True

    def set_version_info_from_source_install(
        self, branch_identifier: str, matcher: Pattern[str]
    ) -> None:
        match = matcher.search(branch_identifier)
        if not match or not match.group("major") or not match.group("minor"):
            fail(
                f"Could not determine dpdk version info from '{self._dpdk_source}'"
                f" with id: '{branch_identifier}' using regex: '{matcher.pattern}'"
            )
        else:
            major, minor = map(int, [match.group("major"), match.group("minor")])
            self._dpdk_version_info = VersionInfo(major, minor)

    def _load_drivers_for_dpdk(self) -> None:
        self.node.log.info("Loading drivers for infiniband, rdma, and mellanox hw...")
        if self.is_connect_x3:
            mellanox_drivers = ["mlx4_core", "mlx4_ib"]
        else:
            mellanox_drivers = ["mlx5_core", "mlx5_ib"]
        modprobe = self.node.tools[Modprobe]
        if isinstance(self.node.os, Ubuntu):
            modprobe.load("rdma_cm")
        elif isinstance(self.node.os, Redhat):
            if not self.is_connect_x3:
                self.node.execute(
                    f"dracut --add-drivers '{' '.join(mellanox_drivers)} ib_uverbs' -f",
                    cwd=self.node.working_path,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "Issue loading mlx and ib_uverb drivers into ramdisk."
                    ),
                    sudo=True,
                )
            modprobe.load("mlx4_en")
        else:
            raise UnsupportedDistroException(self.node.os)
        modprobe.load(["ib_core", "ib_uverbs", "rdma_ucm", "ib_umad", "ib_ipoib"])
        modprobe.load(mellanox_drivers)

    def _install_dependencies(self) -> None:
        node = self.node
        cwd = node.working_path

        if isinstance(node.os, Ubuntu):
            if "18.04" in node.os.information.release:
                node.os.install_packages(list(self._ubuntu_packages_1804))
                self.__execute_assert_zero("pip3 install --upgrade meson", cwd)
                self.__execute_assert_zero("mv /usr/bin/meson /usr/bin/meson.bak", cwd)
                self.__execute_assert_zero(
                    "ln -s /usr/local/bin/meson /usr/bin/meson", cwd
                )
                self.__execute_assert_zero("pip3 install --upgrade ninja", cwd)
            elif "20.04" in node.os.information.release:
                # 20-04 requires backports to be added for dpdk related fixes
                node.execute(
                    "sudo add-apt-repository ppa:canonical-server/server-backports -y",
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "Could not add backports repo."
                    ),
                )
                node.execute(
                    "sudo apt-get update -y",
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "Error with apt-get update (post-backports repo add)"
                    ),
                )
                node.os.install_packages(list(self._ubuntu_packages_2004))

        elif isinstance(node.os, Redhat):
            self.__execute_assert_zero(
                "yum update -y --disablerepo='*' --enablerepo='*microsoft*'", cwd
            )
            node.os.group_install_packages("Development Tools")
            node.os.group_install_packages("Infiniband Support")
            # TODO: Workaround for type checker below
            node.os.install_packages(list(self._redhat_packages))

            self.__execute_assert_zero("systemctl enable rdma", cwd)
            self.__execute_assert_zero("pip3 install --upgrade meson", cwd)
            self.__execute_assert_zero("ln -s /usr/local/bin/meson /usr/bin/meson", cwd)

            wget_tool = self.node.tools[Wget]
            wget_tool.get(
                self._ninja_url,
                file_path=cwd.as_posix(),
                filename="ninja-linux.zip",
            )
            # node.execute(f"mv ninja-linux.zip {node.working_path}/")
            self.__execute_assert_zero(
                "unzip ninja-linux.zip && mv ninja /usr/bin/ninja", cwd
            )
            self.__execute_assert_zero("pip3 install --upgrade pyelftools", cwd)
        else:
            raise UnsupportedDistroException(node.os)

    def generate_testpmd_include(
        self,
        node_nic: NicInfo,
        vdev_id: int,
    ) -> str:
        # handle generating different flags for pmds/device combos for testpmd
        assert_that(node_nic.lower).described_as(
            (
                f"This interface {node_nic.upper} does not have a lower interface "
                "and pci slot associated with it. Aborting."
            )
        ).is_not_equal_to("")
        vdev_info = ""

        if self._dpdk_version_info and self._dpdk_version_info >= "19.11.0":
            vdev_name = "net_vdev_netvsc"
        else:
            vdev_name = "net_failsafe"

        if self._dpdk_version_info and self._dpdk_version_info >= "20.11.0":
            allow_flag = "--allow"
        else:
            allow_flag = "-w"

        if node_nic.bound_driver == "hv_netvsc":
            vdev_info = f'--vdev="{vdev_name}{vdev_id},iface={node_nic.upper}"'
        elif node_nic.bound_driver == "uio_hv_generic":
            pass
        else:
            fail(
                (
                    f"Unknown driver({node_nic.bound_driver}) bound to "
                    f"{node_nic.upper}/{node_nic.lower}."
                    "Cannot generate testpmd include arguments."
                )
            )
        return vdev_info + f' {allow_flag} "{node_nic.pci_slot}"'

    def generate_testpmd_command(
        self,
        nic_to_include: NicInfo,
        vdev_id: int,
        mode: str,
        pmd: str,
        extra_args: str = "",
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
        self.timer_proc = self.node.execute_async(
            f"sleep {timeout} && killall -s INT {cmd.split()[0]}",
            sudo=True,
            shell=True,
        )
        testpmd_proc = self.node.execute_async(
            cmd,
            sudo=True,
        )
        self.timer_proc.wait_result()
        proc_result = testpmd_proc.wait_result()
        self._last_run_output = proc_result.stdout
        return proc_result.stdout

    def kill_previous_testpmd_command(self) -> None:
        # kill testpmd early, then kill the timer proc that is still running
        assert_that(self.timer_proc).described_as(
            "Timer process was not initialized before "
            "calling kill_previous_testpmd_command"
        ).is_not_none()
        self.node.execute(f"killall -s INT {self.command}", sudo=True, shell=True)
        self.timer_proc.kill()

    TX_PPS_KEY = "transmit-packets-per-second"
    RX_PPS_KEY = "receive-packets-per-second"

    testpmd_output_regex = {
        TX_PPS_KEY: r"Tx-pps:\s+([0-9]+)",
        RX_PPS_KEY: r"Rx-pps:\s+([0-9]+)",
    }

    def get_from_testpmd_output(
        self, search_key_constant: str, testpmd_output: str
    ) -> int:
        assert_that(testpmd_output).described_as(
            "Could not find output from last testpmd run."
        ).is_not_equal_to("")
        matches = re.findall(
            self.testpmd_output_regex[search_key_constant], testpmd_output
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
        return self.get_from_testpmd_output(self.RX_PPS_KEY, self._last_run_output)

    def get_tx_pps(self) -> int:
        return self.get_from_testpmd_output(self.TX_PPS_KEY, self._last_run_output)

    def _split_testpmd_output(self) -> None:
        search_str = "Port 0: device removal event"

        device_removal_index = self._last_run_output.find(search_str)
        assert_that(device_removal_index).described_as(
            "Could not locate SRIOV rescind event in testpmd output"
        ).is_not_equal_to(-1)

        self._testpmd_output_before_rescind = self._last_run_output[
            :device_removal_index
        ]
        after_rescind = self._last_run_output[device_removal_index:]
        # Identify the device add event
        hotplug_match = self._search_hotplug_regex.search(after_rescind)
        if not hotplug_match:
            raise LisaException(
                "Could not identify vf hotplug events in testpmd output."
            )

        self.node.log.info(f"Identified hotplug event: {hotplug_match.group(0)}")

        before_reenable = after_rescind[: hotplug_match.start()]
        after_reenable = after_rescind[hotplug_match.end() :]
        self._testpmd_output_during_rescind = before_reenable
        self._testpmd_output_after_reenable = after_reenable

    def _get_pps_sriov_rescind(
        self,
        key_constant: str,
    ) -> Tuple[int, int, int]:
        if not all(
            [
                self._testpmd_output_during_rescind,
                self._testpmd_output_after_reenable,
                self._testpmd_output_before_rescind,
            ]
        ):
            self._split_testpmd_output()

        before_rescind = self.get_from_testpmd_output(
            key_constant, self._testpmd_output_before_rescind
        )
        during_rescind = self.get_from_testpmd_output(
            key_constant, self._testpmd_output_during_rescind
        )
        after_reenable = self.get_from_testpmd_output(
            key_constant, self._testpmd_output_after_reenable
        )
        return before_rescind, during_rescind, after_reenable

    def get_tx_pps_sriov_rescind(self) -> Tuple[int, int, int]:
        return self._get_pps_sriov_rescind(self.TX_PPS_KEY)

    def get_rx_pps_sriov_rescind(self) -> Tuple[int, int, int]:
        return self._get_pps_sriov_rescind(self.RX_PPS_KEY)
