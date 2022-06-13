# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from functools import partial
from pathlib import PurePosixPath
from typing import List, Pattern, Tuple, Type, Union

from assertpy import assert_that, fail
from semver import VersionInfo

from lisa.executable import Tool
from lisa.nic import NicInfo
from lisa.node import Node
from lisa.operating_system import Debian, Fedora, Oracle, Redhat, Suse, Ubuntu
from lisa.tools import (
    Echo,
    Git,
    Kill,
    Lscpu,
    Lspci,
    Modprobe,
    Pidof,
    Service,
    Tar,
    Unzip,
    Wget,
)
from lisa.util import (
    LisaException,
    MissingPackagesException,
    SkippedException,
    UnsupportedDistroException,
)
from lisa.util.parallel import TaskManager, run_in_parallel_async
from lisa.util.perf_timer import create_timer

PACKAGE_MANAGER_SOURCE = "package_manager"


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

    _testpmd_install_path = ""
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

    # these are the same at the moment but might need tweaking later
    _debian_packages = _ubuntu_packages_2004

    _redhat_packages = [
        "psmisc",
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
        for _os in [Ubuntu, Fedora]:
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

    def get_dpdk_version(self) -> VersionInfo:
        return self._dpdk_version_info

    def has_tx_ip_flag(self) -> bool:
        dpdk_version = self.get_dpdk_version()
        if not dpdk_version:
            fail(
                "Test suite bug: dpdk version was not set prior "
                "to querying the version information."
            )

        # black doesn't like to direct return VersionInfo comparison
        return bool(dpdk_version >= "19.11.0")  # appease the type checker

    def use_package_manager_install(self) -> bool:
        assert_that(hasattr(self, "_dpdk_source")).described_as(
            "_dpdk_source was not set in DpdkTestpmd instance. "
            "set_dpdk_source must be called before instantiation."
        ).is_true()
        return self._dpdk_source == PACKAGE_MANAGER_SOURCE

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
        use_core_count: int = 0,
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

        # dpdk can use multiple cores to service the
        # number of queues and ports present. Get the amount to work with.
        cores_available = self.node.tools[Lscpu].get_core_count()

        # default is to use cores 0 and 1
        core_count_arg = 2

        # queue test forces multicore, use_core_count can override it if needed.
        if txq or rxq:

            # set number of queues to use for tx and rx
            assert_that(txq).described_as(
                "TX queue value must be greater than 0 if txq is used"
            ).is_greater_than(0)
            assert_that(rxq).described_as(
                "RX queue value must be greater than 0 if rxq is used"
            ).is_greater_than(0)
            extra_args += f" --txq={txq} --rxq={rxq}  --port-topology=chained "

            # use either as many cores as we can or one for each queue and port
            core_count_arg = min(cores_available, core_count_arg + txq + rxq)

        # force set number of cores if the override argument is present.
        if use_core_count:
            core_count_arg = use_core_count

        # check cores_to_use argument is sane, 2 < arg <= number_available
        assert_that(core_count_arg).described_as(
            "Attempted to use more cores than are available on the system for DPDK."
        ).is_less_than_or_equal_to(cores_available)
        assert_that(core_count_arg).described_as(
            "DPDK requires a minimum of two cores."
        ).is_greater_than(1)

        # use the selected amount of cores, adjusting for 0 index.
        core_args = f"-l 0-{core_count_arg-1}"

        return (
            f"{self._testpmd_install_path} {core_args} -n 4 --proc-type=primary "
            f"{nic_include_info} -- --forward-mode={mode} {extra_args} "
            "-a --stats-period 1"
        )

    def run_for_n_seconds(self, cmd: str, timeout: int) -> str:
        self._last_run_timeout = timeout
        self.node.log.info(f"{self.node.name} running: {cmd}")

        # run testpmd async
        testpmd_proc = self.node.execute_async(
            cmd,
            sudo=True,
        )

        # setup a timer
        self.killer = create_async_timeout(self.node, self.command, timeout)

        # wait for killer to finish (or be canceled)
        self.killer.wait_for_all_workers()
        proc_result = testpmd_proc.wait_result()
        self._last_run_output = proc_result.stdout
        self.populate_performance_data()
        return proc_result.stdout

    def check_testpmd_is_running(self) -> bool:
        pids = self.node.tools[Pidof].get_pids(self.command, sudo=True)
        return len(pids) > 0

    def kill_previous_testpmd_command(self) -> None:
        # kill testpmd early
        if not hasattr(self, "killer"):
            fail(
                "Test Suite Error: kill_previous_testpmd_command was called"
                " but there was no task killer registered."
            )
        # cancel the scheduled killer
        self.killer.cancel()
        # and kill immediately
        self.node.tools[Kill].by_name(self.command)
        if self.check_testpmd_is_running():
            raise LisaException(
                "Testpmd is not responding to signals, failing the test."
            )

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
        if isinstance(node.os, Debian):
            self._debian_backports_args = [
                f"-t {node.os.information.codename}-backports"
            ]
        self._install_dependencies()
        # installing from distro package manager
        if self.use_package_manager_install():
            self.node.log.info(
                "Installing dpdk and dev package from package manager..."
            )
            if isinstance(node.os, Debian):
                node.os.install_packages(
                    ["dpdk", "dpdk-dev"],
                    extra_args=self._debian_backports_args,
                )
            elif isinstance(node.os, Fedora):
                node.os.install_packages(["dpdk", "dpdk-devel"])
            else:
                raise NotImplementedError(
                    "Dpdk package names are missing in dpdktestpmd.install"
                    f" for os {node.os.name}"
                )

            self._dpdk_version_info = node.os.get_package_information("dpdk")

            self.node.log.info(
                f"Installed DPDK version {str(self._dpdk_version_info)} "
                "from package manager"
            )
            self.find_testpmd_binary()
            self._load_drivers_for_dpdk()
            return True

        # otherwise install from source tarball or git
        self.node.log.info(f"Installing dpdk from source: {self._dpdk_source}")
        self._dpdk_repo_path_name = "dpdk"
        self.dpdk_path = self.node.working_path.joinpath(self._dpdk_repo_path_name)

        if self.find_testpmd_binary(
            assert_on_fail=False
        ):  # tools are already installed
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
            if not self._dpdk_branch:

                # dpdk stopped using a default branch
                # if a branch is not specified, get latest version tag.
                self._dpdk_branch = git_tool.get_tag(
                    self.dpdk_path, filter=r"^v.*"  # starts w 'v'
                )

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
            timeout=1800,
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

        self.find_testpmd_binary(check_path="/usr/local/bin")

        return True

    def _load_drivers_for_dpdk(self) -> None:
        self.node.log.info("Loading drivers for infiniband, rdma, and mellanox hw...")
        if self.is_connect_x3:
            mellanox_drivers = ["mlx4_core", "mlx4_ib"]
        else:
            mellanox_drivers = ["mlx5_core", "mlx5_ib"]
        modprobe = self.node.tools[Modprobe]
        if isinstance(self.node.os, Ubuntu):
            # Ubuntu shouldn't need any special casing, skip to loading rdma/ib
            pass
        elif isinstance(self.node.os, Debian):
            # NOTE: debian buster doesn't include rdma and ib drivers
            # on 5.4 specifically for linux-image-cloud:
            # https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1012639
            # for backports on this release we should update the kernel to latest
            kernel_info = self.node.os.get_kernel_information(force_run=True)
            # update to at least 5.10 (known good for buster linux-image-cloud-(arch))
            if (
                self.node.os.information.codename == "buster"
                and kernel_info.version <= "5.10.0"
            ):
                self.node.log.debug(
                    f"Debian (buster) kernel version found: {str(kernel_info.version)} "
                    "Updating linux-image-cloud to most recent kernel."
                )
                # grab the linux-image package name from kernel version metadata
                linux_image_package = "linux-image-cloud-[a-zA-Z0-9]*"
                self.node.os.install_packages([linux_image_package])
                self.node.reboot()
        elif isinstance(self.node.os, Fedora):
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
        else:
            raise UnsupportedDistroException(self.node.os)
        rmda_drivers = ["ib_core", "ib_uverbs", "rdma_ucm"]

        # some versions of dpdk require these two, some don't.
        # some systems have them, some don't. Load if they're there.
        for module in ["ib_ipoib", "ib_umad"]:
            if modprobe.module_exists(module):
                rmda_drivers.append(module)

        modprobe.load(rmda_drivers)
        modprobe.load(mellanox_drivers)

    def check_dpdk_support(self) -> None:
        # check requirements according to:
        # https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk
        node = self.node
        supported = False
        if isinstance(node.os, Debian):
            if isinstance(node.os, Ubuntu):
                supported = node.os.information.version >= "18.4.0"
            else:
                supported = node.os.information.version >= "10.0.0"
        elif isinstance(node.os, Redhat) and not isinstance(node.os, Oracle):
            supported = node.os.information.version >= "7.5.0"
        elif isinstance(node.os, Suse):
            supported = node.os.information.version >= "15.0.0"
        else:
            # this OS is not supported
            raise UnsupportedDistroException(
                node.os, "This OS is not supported by the DPDK test suite for Azure."
            )

        if not supported:
            raise UnsupportedDistroException(
                node.os, "This OS version is EOL and is not supported for DPDK on Azure"
            )

    def _install_dependencies(self) -> None:
        node = self.node
        self.check_dpdk_support()  # will skip if OS is not supported
        if isinstance(node.os, Ubuntu):
            self._install_ubuntu_dependencies()
        elif isinstance(node.os, Debian):
            node.os.install_packages(
                list(self._debian_packages), extra_args=self._debian_backports_args
            )
        elif isinstance(node.os, Redhat):
            self._install_redhat_dependencies()
        else:
            raise UnsupportedDistroException(
                node.os, "This OS does not have dpdk installation implemented yet."
            )

    def _install_ubuntu_dependencies(self) -> None:
        node = self.node
        ubuntu = node.os
        if not isinstance(ubuntu, Ubuntu):
            fail(
                "_install_ubuntu_dependencies was called on node "
                f"which was not Ubuntu: {node.os.information.full_version}"
            )
            return  # appease the type checker
        if ubuntu.information.version < "18.4.0":
            raise SkippedException(
                f"Ubuntu {str(ubuntu.information.version)} is not supported. "
                "Minimum documented version for DPDK support is >=18.04"
            )
        elif ubuntu.information.version < "20.4.0":
            ubuntu.install_packages(
                list(self._ubuntu_packages_1804),
                extra_args=self._debian_backports_args,
            )
            if not self.use_package_manager_install():
                self._install_ninja_and_meson()
        else:
            ubuntu.install_packages(
                list(self._ubuntu_packages_2004),
                extra_args=self._debian_backports_args,
            )

    def _install_redhat_dependencies(self) -> None:
        node = self.node
        rhel = node.os
        if not isinstance(rhel, Redhat):
            fail(
                "_install_redhat_dependencies was called on node "
                f"which was not Redhat: {node.os.information.full_version}"
            )
            return  # appease the type checker

        if rhel.information.version.major == 7:
            # Add packages for rhel7
            rhel.install_packages(list(["libmnl-devel", "libbpf-devel"]))

        try:
            rhel.install_packages("kernel-devel-$(uname -r)")
        except MissingPackagesException:
            node.log.debug("kernel-devel-$(uname -r) not found. Trying kernel-devel")
            rhel.install_packages("kernel-devel")

        # RHEL 8 doesn't require special cases for installed packages.
        # TODO: RHEL9 may require updates upon release

        rhel.group_install_packages("Development Tools")
        rhel.group_install_packages("Infiniband Support")
        rhel.install_packages(list(self._redhat_packages))

        # ensure RDMA service is started if present.

        service_name = "rdma"
        service = node.tools[Service]
        if service.check_service_exists(service_name):
            if not service.check_service_status(service_name):
                service.enable_service(service_name)

            # some versions of RHEL and CentOS have service.rdma
            # that will refuse manual start/stop and will return
            # NOPERMISSION. This is not fatal and can be continued.
            # If the service is present it should start when needed.
            service.restart_service(
                service_name, ignore_exit_code=service.SYSTEMD_EXIT_NOPERMISSION
            )

        if not self.use_package_manager_install():
            self._install_ninja_and_meson()

    def _install_ninja_and_meson(self) -> None:
        node = self.node
        cwd = node.working_path
        node.execute(
            "pip3 install --upgrade meson",
            cwd=cwd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to update Meson to latest version with pip3"
            ),
        )
        if node.shell.exists(node.get_pure_path("/usr/bin/meson")):
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
                "Failed to link new meson version as the " "default version in /usr/bin"
            ),
        )
        # NOTE: finding latest ninja is a pain,
        # so just fetch latest from github here
        wget_tool = self.node.tools[Wget]
        wget_tool.get(
            self._ninja_url,
            file_path=cwd.as_posix(),
            filename="ninja-linux.zip",
        )
        node.tools[Unzip].extract(
            file=str(cwd.joinpath("ninja-linux.zip")),
            dest_dir=str(cwd),
            sudo=True,
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

    def find_testpmd_binary(
        self, check_path: str = "", assert_on_fail: bool = True
    ) -> bool:
        node = self.node
        if self._testpmd_install_path:
            return True
        for bin_name in ["dpdk-testpmd", "testpmd"]:
            if check_path:
                bin_path = PurePosixPath(check_path).joinpath(bin_name)
                bin_name = str(bin_path)
            result = node.execute(f"which {bin_name}")
            if result.exit_code == 0:
                self._testpmd_install_path = result.stdout.strip()
                break
        found_path = PurePosixPath(self._testpmd_install_path)
        path_check = bool(self._testpmd_install_path) and node.shell.exists(found_path)
        if assert_on_fail and not path_check:
            fail("Could not locate testpmd binary after installation!")
        elif not path_check:
            self._testpmd_install_path = ""
        return path_check

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


# Cancellable timeout tool
def create_async_timeout(node: Node, command: str, timeout: int) -> TaskManager[None]:

    # setup a timer
    def kill_timer(timeout: int) -> None:
        timer = create_timer()
        while timer.elapsed(False) < timeout:
            pass

    # and killer callback, callback will not run if timer is cancelled
    def kill_callback(x: None) -> None:
        node.tools[Kill].by_name(command)

    # initiate async timer
    kill_manager = run_in_parallel_async(
        [partial(kill_timer, timeout)], kill_callback, node.log
    )

    return kill_manager
