# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List, Pattern, Tuple, Type, Union

from assertpy import assert_that, fail
from semver import VersionInfo

from lisa.executable import Tool
from lisa.nic import NicInfo
from lisa.operating_system import CentOs, Redhat, Ubuntu
from lisa.tools import Echo, Git, Lscpu, Lspci, Modprobe, Service, Tar, Wget
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
        "elfutils-libelf-devel",
        "python3-pip",
        "kernel-modules-extra",
        "kernel-headers",
    ]
    _rte_target = "x86_64-native-linuxapp-gcc"
    _ninja_url = (
        "https://github.com/ninja-build/ninja/releases/"
        "download/v1.10.2/ninja-linux.zip"
    )

    _tx_pps_key = "transmit-packets-per-second"
    _rx_pps_key = "receive-packets-per-second"

    _testpmd_output_regex = {
        _tx_pps_key: r"Tx-pps:\s+([0-9]+)",
        _rx_pps_key: r"Rx-pps:\s+([0-9]+)",
    }

    @property
    def can_install(self) -> bool:
        for _os in [Ubuntu, CentOs, Redhat]:
            if isinstance(self.node.os, _os):
                return True
        return False

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Wget, Lscpu]

    def set_dpdk_source(self, dpdk_source: str) -> None:
        self._dpdk_source = dpdk_source

    def set_dpdk_branch(self, dpdk_branch: str) -> None:
        self._dpdk_branch = dpdk_branch

    def get_dpdk_branch(self) -> VersionInfo:
        return self._dpdk_version_info

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
        txq: int = 0,
        rxq: int = 0,
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
        if txq or rxq:
            assert_that(txq).described_as(
                "TX queue value must be greater than 0 if txq is used"
            ).is_greater_than(0)
            assert_that(rxq).described_as(
                "RX queue value must be greater than 0 if rxq is used"
            ).is_greater_than(0)
            extra_args += f" --txq={txq} --rxq={rxq}  --port-topology=chained "
            cores_to_use = self.node.tools[Lscpu].get_core_count()
            assert_that(cores_to_use).described_as(
                f"DPDK requires a minimum of 8 cores, found {cores_to_use}"
            ).is_greater_than(8)
            core_args = f"-l 0-{cores_to_use-1}"
        else:
            core_args = "-l 0-1"

        return (
            f"{self._testpmd_install_path} {core_args} -n 4 --proc-type=primary "
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
        self.populate_performance_data()
        return proc_result.stdout

    def kill_previous_testpmd_command(self) -> None:
        # kill testpmd early, then kill the timer proc that is still running
        assert_that(self.timer_proc).described_as(
            "Timer process was not initialized before "
            "calling kill_previous_testpmd_command"
        ).is_not_none()
        self.node.execute(f"killall -s INT {self.command}", sudo=True, shell=True)
        self.timer_proc.kill()

    def get_data_from_testpmd_output(
        self,
        search_key_constant: str,
        testpmd_output: str,
    ) -> List[int]:
        # Find all data in the output that matches
        # Apply a list of filters to the data
        # return a single output from a final filter function
        assert_that(testpmd_output).described_as(
            "Could not find output from last testpmd run."
        ).is_not_equal_to("")
        matches = re.findall(
            self._testpmd_output_regex[search_key_constant], testpmd_output
        )
        assert_that(matches).described_as(
            (
                "Could not locate any matches for search key "
                f"{self._testpmd_output_regex[search_key_constant]} "
                "in the test output."
            )
        )
        cast_to_ints = list(map(int, matches))
        return _discard_first_zeroes(cast_to_ints)

    def populate_performance_data(self) -> None:
        self.rx_pps_data = self.get_data_from_testpmd_output(
            self._rx_pps_key, self._last_run_output
        )
        self.tx_pps_data = self.get_data_from_testpmd_output(
            self._tx_pps_key, self._last_run_output
        )

    def get_mean_rx_pps(self) -> int:
        self._check_pps_data("RX")
        return _mean(self.rx_pps_data)

    def get_mean_tx_pps(self) -> int:
        self._check_pps_data("TX")
        return _mean(self.tx_pps_data)

    def get_max_rx_pps(self) -> int:
        self._check_pps_data("RX")
        return max(self.rx_pps_data)

    def get_max_tx_pps(self) -> int:
        self._check_pps_data("TX")
        return max(self.tx_pps_data)

    def get_min_rx_pps(self) -> int:
        self._check_pps_data("RX")
        return min(self.rx_pps_data)

    def get_min_tx_pps(self) -> int:
        self._check_pps_data("TX")
        return min(self.tx_pps_data)

    def get_mean_tx_pps_sriov_rescind(self) -> Tuple[int, int, int]:
        return self._get_pps_sriov_rescind(self._tx_pps_key)

    def get_mean_rx_pps_sriov_rescind(self) -> Tuple[int, int, int]:
        return self._get_pps_sriov_rescind(self._rx_pps_key)

    def add_sample_apps_to_build_list(self, apps: Union[List[str], None]) -> None:
        if apps:
            self._sample_apps_to_build = apps
        else:
            self._sample_apps_to_build = []

    def _determine_network_hardware(self) -> None:
        lspci = self.node.tools[Lspci]
        device_list = lspci.get_devices()
        self.is_connect_x3 = any(
            ["ConnectX-3" in dev.device_info for dev in device_list]
        )

    def _check_pps_data_exists(self, rx_or_tx: str) -> None:
        data_attr_name = f"{rx_or_tx.lower()}_pps_data"
        assert_that(hasattr(self, data_attr_name)).described_as(
            (
                f"PPS data ({rx_or_tx}) did not exist for testpmd object. "
                "This indicates either testpmd did not run or the suite is "
                "missing an assert. Contact the test maintainer."
            )
        ).is_true()

    def _check_pps_data(self, rx_or_tx: str) -> None:
        self._check_pps_data_exists(rx_or_tx)
        data_set: List[int] = []
        if rx_or_tx == "RX":
            data_set = self.rx_pps_data
        elif rx_or_tx == "TX":
            data_set = self.tx_pps_data
        else:
            fail(
                "Identifier passed to _check_pps_data was not recognized, "
                f"must be RX or TX. Found {rx_or_tx}"
            )

        assert_that(any(data_set)).described_as(
            f"any({str(data_set)}) resolved to false. Test data was "
            f"empty or all zeroes for dpdktestpmd.{rx_or_tx.lower()}_pps_data."
        ).is_true()

    def _install(self) -> bool:
        self._testpmd_output_after_reenable = ""
        self._testpmd_output_before_rescind = ""
        self._testpmd_output_during_rescind = ""
        self._last_run_output = ""
        self._determine_network_hardware()
        node = self.node
        self._install_dependencies()
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
            self.node.log.info(
                f"Installed DPDK version {str(self._dpdk_version_info)} "
                "from package manager"
            )
            self._load_drivers_for_dpdk()
            return True

        # otherwise install from source tarball or git
        self.node.log.info(f"Installing dpdk from source: {self._dpdk_source}")
        self._dpdk_repo_path_name = "dpdk"
        result = self.node.execute("which dpdk-testpmd")
        self.dpdk_path = self.node.working_path.joinpath(self._dpdk_repo_path_name)
        if result.exit_code == 0:  # tools are already installed
            return True
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

        # add sample apps to compilation if they are present
        if self._sample_apps_to_build:
            sample_apps = f"-Dexamples={','.join(self._sample_apps_to_build)}"
        else:
            sample_apps = ""

        node.execute(
            f"meson {sample_apps} build",
            shell=True,
            cwd=self.dpdk_path,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "meson build for dpdk failed, check that"
                "dpdk build has not changed to eliminate the use of meson or "
                "meson version is compatible with this dpdk version and OS."
            ),
        )
        self.dpdk_build_path = self.dpdk_path.joinpath("build")
        node.execute(
            "ninja",
            cwd=self.dpdk_build_path,
            timeout=1200,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "ninja build for dpdk failed. check build spew for missing headers "
                "or dependencies. Also check that this ninja version requirement "
                "has not changed for dpdk."
            ),
        )
        node.execute(
            "ninja install",
            cwd=self.dpdk_build_path,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "ninja install failed for dpdk binaries."
            ),
        )
        node.execute(
            "ldconfig",
            cwd=self.dpdk_build_path,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="ldconfig failed, check for error spew.",
        )
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
            node.os.add_repository("ppa:canonical-server/server-backports")
            if "18.04" in node.os.information.release:
                node.os.install_packages(list(self._ubuntu_packages_1804))
                # ubuntu 18 has some issue with the packaged versions of meson
                # and ninja. To guarantee latest, install and update with pip3
                node.execute(
                    "pip3 install --upgrade meson",
                    cwd=cwd,
                    sudo=True,
                    shell=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "pip3 install failed to upgrade meson to newest version."
                    ),
                )
                node.execute(
                    "mv /usr/bin/meson /usr/bin/meson.bak",
                    cwd=cwd,
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "renaming previous meson binary or link in /usr/bin/meson"
                        " failed."
                    ),
                )
                node.execute(
                    "ln -s /usr/local/bin/meson /usr/bin/meson",
                    cwd=cwd,
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "could not link new meson binary to /usr/bin/meson"
                    ),
                )
                node.execute(
                    "pip3 install --upgrade ninja",
                    cwd=cwd,
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "pip3 upgrade for ninja failed"
                    ),
                )
            elif "20.04" in node.os.information.release:
                node.os.install_packages(list(self._ubuntu_packages_2004))

        elif isinstance(node.os, Redhat):
            if node.os.information.version.major < 7:
                raise UnsupportedDistroException(
                    node.os, "DPDK for Redhat < 7 is not supported by this test"
                )
            elif node.os.information.version.major == 7:
                # Add packages for rhel7
                node.os.install_packages(list(["libmnl-devel", "libbpf-devel"]))

            # RHEL 8 doesn't require special cases for installed packages.
            # TODO: RHEL9 may require updates upon release

            node.os.group_install_packages("Development Tools")
            node.os.group_install_packages("Infiniband Support")
            node.os.install_packages(list(self._redhat_packages))

            # ensure RDMA service is started if present.
            service_name = "rdma"
            service = node.tools[Service]
            if service.check_service_exists(service_name):
                service.restart_service(service_name)

            node.execute(
                "pip3 install --upgrade meson",
                cwd=cwd,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Failed to update Meson to latest version with pip3"
                ),
            )
            node.execute(
                "ln -s /usr/local/bin/meson /usr/bin/meson",
                cwd=cwd,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Failed to link new meson version as the "
                    "default version in /usr/bin"
                ),
            )
            # NOTE: finding latest ninja on RH is a pain,
            # so just fetch latest from github here
            wget_tool = self.node.tools[Wget]
            wget_tool.get(
                self._ninja_url,
                file_path=cwd.as_posix(),
                filename="ninja-linux.zip",
            )
            node.execute(
                "unzip ninja-linux.zip",
                cwd=cwd,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Failed to unzip latest ninja-linux.zip from github."
                ),
            )
            node.execute(
                "mv ninja /usr/bin/ninja",
                cwd=cwd,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Could not move latest ninja script after unzip into /usr/bin."
                ),
            )
            node.execute(
                "pip3 install --upgrade pyelftools",
                sudo=True,
                cwd=cwd,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Could not upgrade pyelftools with pip3."
                ),
            )
        else:
            raise UnsupportedDistroException(node.os)

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

        before_rescind = self.get_data_from_testpmd_output(
            key_constant,
            self._testpmd_output_before_rescind,
        )
        during_rescind = self.get_data_from_testpmd_output(
            key_constant,
            self._testpmd_output_during_rescind,
        )
        after_reenable = self.get_data_from_testpmd_output(
            key_constant,
            self._testpmd_output_after_reenable,
        )
        before, during, after = map(
            _mean, [before_rescind, during_rescind, after_reenable]
        )
        return before, during, after


# filter functions for processing testpmd data
def _discard_first_zeroes(data: List[int]) -> List[int]:
    # NOTE: we occasionally get a 0 for the first pps result sample,
    # it's annoying to factor it into the average when
    # there are only like 10 samples so discard any
    # leading 0's if they're present.

    for i in range(len(data)):
        if data[i] != 0:
            return data[i:]

    # leave list as-is if data is all zeroes
    return data


def _mean(data: List[int]) -> int:
    return sum(data) // len(data)
