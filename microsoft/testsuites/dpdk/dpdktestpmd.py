# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePosixPath
from typing import Any, List, Pattern, Tuple, Type, Union

from assertpy import assert_that, fail
from semver import VersionInfo

from lisa.base_tools import Mv
from lisa.executable import ExecutableResult, Tool
from lisa.nic import NicInfo
from lisa.operating_system import Debian, Fedora, Suse, Ubuntu
from lisa.tools import (
    Echo,
    Git,
    Kill,
    Lscpu,
    Lspci,
    Modprobe,
    Pidof,
    Rm,
    Service,
    Tar,
    Timeout,
    Wget,
)
from lisa.util import (
    LisaException,
    MissingPackagesException,
    SkippedException,
    UnsupportedDistroException,
)
from lisa.util.constants import SIGINT

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
    _search_hotplug_regex_alt = re.compile(
        r"EAL: PCI device [a-fA-F0-9]{4}:[a-fA-F0-9]{2}:[a-fA-F0-9]{2}\.[a-fA-F0-9] "
        r"on NUMA socket [0-9]+"
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
        if not self._testpmd_install_path:
            return "testpmd"
        return self._testpmd_install_path

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

    _fedora_packages = [
        "psmisc",
        "numactl-devel",
        "librdmacm-devel",
        "pkgconfig",
        "elfutils-libelf-devel",
        "python3-pip",
        "kernel-modules-extra",
        "kernel-headers",
        "gcc-c++",
    ]
    _suse_packages = [
        "psmisc",
        "libnuma-devel",
        "numactl",
        "librdmacm1",
        "rdma-core-devel",
        "libmnl-devel meson",
        "gcc-c++",
    ]
    _rte_target = "x86_64-native-linuxapp-gcc"
    _ninja_url = "https://github.com/ninja-build/ninja/"

    _tx_pps_key = "transmit-packets-per-second"
    _rx_pps_key = "receive-packets-per-second"

    _testpmd_output_regex = {
        _tx_pps_key: r"Tx-pps:\s+([0-9]+)",
        _rx_pps_key: r"Rx-pps:\s+([0-9]+)",
    }

    @property
    def can_install(self) -> bool:
        for _os in [Debian, Fedora, Suse]:
            if isinstance(self.node.os, _os):
                return True
        return False

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Wget, Lscpu]

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
        if self._dpdk_source == PACKAGE_MANAGER_SOURCE:
            return True
        else:
            return False

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
            self._dpdk_version_info: VersionInfo = VersionInfo(major, minor)

    def generate_testpmd_include(self, node_nic: NicInfo, vdev_id: int) -> str:
        # handle generating different flags for pmds/device combos for testpmd

        # identify which nics to inlude in test, exclude others
        include_nics = [node_nic]
        exclude_nics = [
            self.node.nics.get_nic(nic)
            for nic in self.node.nics.get_upper_nics()
            if nic != node_nic.upper
        ]

        # build list of vdev info flags for each nic
        vdev_info = ""
        self.node.log.info(f"Running test with {len(include_nics)} nics.")
        for nic in include_nics:
            if self._dpdk_version_info and self._dpdk_version_info >= "18.11.0":
                vdev_name = "net_vdev_netvsc"
                vdev_flags = f"iface={nic.upper},force=1"
            else:
                vdev_name = "net_failsafe"
                vdev_flags = (
                    f"dev({nic.pci_slot}),dev(net_tap0,iface={nic.upper},force=1)"
                )
            if nic.bound_driver == "hv_netvsc":
                vdev_info += f'--vdev="{vdev_name}{vdev_id},{vdev_flags}" '
            elif nic.bound_driver == "uio_hv_generic":
                pass
            else:
                fail(
                    (
                        f"Unknown driver({nic.bound_driver}) bound to "
                        f"{nic.upper}/{nic.lower}."
                        "Cannot generate testpmd include arguments."
                    )
                )

        # exclude pci slots not associated with the test nic
        exclude_flags = ""
        for nic in exclude_nics:
            exclude_flags += f' -b "{nic.pci_slot}"'

        return vdev_info + exclude_flags

    def generate_testpmd_command(
        self,
        nic_to_include: NicInfo,
        vdev_id: int,
        mode: str,
        extra_args: str = "",
        multiple_queues: bool = False,
        service_cores: int = 1,
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

        if multiple_queues:
            txq = 4
            rxq = 4
        else:
            txq = 1
            rxq = 1

        nic_include_info = self.generate_testpmd_include(nic_to_include, vdev_id)

        # infer core count to assign based on number of queues
        cores_available = self.node.tools[Lscpu].get_core_count()
        assert_that(cores_available).described_as(
            "DPDK tests need more than 4 cores, recommended more than 8 cores"
        ).is_greater_than(4)

        # EAL core model is logical cores, so one thread per EAL 'core'
        threads_per_core = max(1, self.node.tools[Lscpu].get_thread_per_core_count())
        logical_cores_available = cores_available * threads_per_core
        queues_and_servicing_core = txq + rxq + service_cores

        # use enough cores for (queues + service core) or max available
        max_core_index = min(
            logical_cores_available - threads_per_core,  # leave one physical for system
            queues_and_servicing_core,
        )

        # service cores excluded from forwarding cores count
        forwarding_cores = max_core_index - service_cores

        # core range argument
        core_list = f"-l 1-{max_core_index}"
        if extra_args:
            extra_args = extra_args.strip()
        else:
            extra_args = ""

        assert_that(forwarding_cores).described_as(
            ("DPDK tests need at least one forwading core. ")
        ).is_greater_than(0)
        assert_that(max_core_index).described_as(
            "Test needs at least 1 core for servicing and one core for forwarding"
        ).is_greater_than(0)

        return (
            f"{self._testpmd_install_path} {core_list} "
            f"{nic_include_info} -- --forward-mode={mode} "
            f"-a --stats-period 2 --nb-cores={forwarding_cores} {extra_args} "
        )

    def run_for_n_seconds(self, cmd: str, timeout: int) -> str:
        self._last_run_timeout = timeout
        self.node.log.info(f"{self.node.name} running: {cmd}")

        proc_result = self.node.tools[Timeout].run_with_timeout(
            cmd, timeout, SIGINT, kill_timeout=timeout + 10
        )
        self._last_run_output = proc_result.stdout
        self.populate_performance_data()
        return proc_result.stdout

    def start_for_n_seconds(self, cmd: str, timeout: int) -> str:
        self._last_run_timeout = timeout
        self.node.log.info(f"{self.node.name} running: {cmd}")

        proc_result = self.node.tools[Timeout].run_with_timeout(
            cmd, timeout, SIGINT, kill_timeout=timeout + 10
        )
        return self.process_testpmd_output(proc_result)

    def process_testpmd_output(self, result: ExecutableResult) -> str:
        self._last_run_output = result.stdout
        self.populate_performance_data()
        return result.stdout

    def check_testpmd_is_running(self) -> bool:
        pids = self.node.tools[Pidof].get_pids(self.command, sudo=True)
        return len(pids) > 0

    def kill_previous_testpmd_command(self) -> None:
        # kill testpmd early
        self.node.tools[Kill].by_name(self.command, ignore_not_exist=True)
        if self.check_testpmd_is_running():
            self.node.log.debug(
                "Testpmd is not responding to signals, "
                "attempt network connection reset."
            )

            # reset node connections (quicker and less risky than netvsc reset)
            self.node.close()
            if not self.check_testpmd_is_running():
                return

            self.node.log.debug(
                "Testpmd is not responding to signals, attempt reload of hv_netvsc."
            )
            # if this somehow didn't kill it, reset netvsc
            self.node.tools[Modprobe].reload(["hv_netvsc"])
            if self.check_testpmd_is_running():
                raise LisaException("Testpmd has hung, killing the test.")
            else:
                self.node.log.debug(
                    "Testpmd killed with hv_netvsc reload. "
                    "Proceeding with processing test run results."
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
        cast_to_ints = _discard_first_zeroes(cast_to_ints)
        return _discard_first_and_last_sample(cast_to_ints)

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._dpdk_source = kwargs.pop("dpdk_source", PACKAGE_MANAGER_SOURCE)
        self._dpdk_branch = kwargs.pop("dpdk_branch", "main")
        self._sample_apps_to_build = kwargs.pop("sample_apps", [])
        self._dpdk_version_info = VersionInfo(0, 0)
        self._testpmd_install_path: str = ""
        if not self.use_package_manager_install():
            self._dpdk_repo_path_name = "dpdk"
            work_path = self.node.get_working_path_with_required_space(5)
            self.current_work_path = self.node.get_pure_path(work_path)
            self.dpdk_path = self.node.get_pure_path(work_path).joinpath(
                self._dpdk_repo_path_name
            )
        self.find_testpmd_binary(assert_on_fail=False)

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
            repos = node.os.get_repositories()
            backport_repo = f"{node.os.information.codename}-backports"
            if any([backport_repo in repo.name for repo in repos]):
                self._debian_backports_args = [f"-t {backport_repo}"]
            else:
                self._debian_backports_args = []
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
            elif isinstance(node.os, (Fedora, Suse)):
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

        if self.find_testpmd_binary(
            assert_on_fail=False, check_path="/usr/local/bin"
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
            wget_tool.get(
                self._dpdk_source,
                str(self.current_work_path),
            )
            dpdk_filename = self._dpdk_source.split("/")[-1]
            # extract tar into dpdk/ folder and discard old root folder name
            tar_tool.extract(
                str(self.current_work_path.joinpath(dpdk_filename)),
                str(self.dpdk_path),
                strip_components=1,
            )
            self.set_version_info_from_source_install(
                self._dpdk_source, self._version_info_from_tarball_regex
            )
        else:
            git_tool.clone(
                self._dpdk_source,
                cwd=self.current_work_path,
                dir_name=self._dpdk_repo_path_name,
            )
            if not self._dpdk_branch:
                # dpdk stopped using a default branch
                # if a branch is not specified, get latest version tag.
                self._dpdk_branch = git_tool.get_tag(
                    self.dpdk_path, filter_=r"^v.*"  # starts w 'v'
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
        if isinstance(self.node.os, (Ubuntu, Suse)):
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

    def _install_dependencies(self) -> None:
        node = self.node
        if isinstance(node.os, Ubuntu):
            self._install_ubuntu_dependencies()
        elif isinstance(node.os, Debian):
            node.os.install_packages(
                self._debian_packages, extra_args=self._debian_backports_args
            )
        elif isinstance(node.os, Fedora):
            self._install_fedora_dependencies()
        elif isinstance(node.os, Suse):
            self._install_suse_dependencies()
        else:
            raise UnsupportedDistroException(
                node.os, "This OS does not have dpdk installation implemented yet."
            )

    def _install_suse_dependencies(self) -> None:
        node = self.node
        suse = node.os
        if not isinstance(suse, Suse):
            fail(
                "_install_suse_dependencies was called on node "
                f"which was not suse: {node.os.information.full_version}"
            )
            return  # appease the type checker
        if suse.information.version < "15.0.0":
            raise SkippedException(
                f"Suse {str(suse.information.version)} is not supported. "
                "Minimum documented version for DPDK support is >= SLES15"
            )
        else:
            suse.install_packages(self._suse_packages)
            if not self.use_package_manager_install():
                self._install_ninja_and_meson()

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
                self._ubuntu_packages_1804,
                extra_args=self._debian_backports_args,
            )
            if not self.use_package_manager_install():
                self._install_ninja_and_meson()
        else:
            ubuntu.install_packages(
                self._ubuntu_packages_2004,
                extra_args=self._debian_backports_args,
            )

    def _install_fedora_dependencies(self) -> None:
        node = self.node
        rhel = node.os
        if not isinstance(rhel, Fedora):
            fail(
                "_install_fedora_dependencies was called on node "
                f"which was not Fedora: {node.os.information.full_version}"
            )
            return  # appease the type checker

        # DPDK is very sensitive to rdma-core/kernel mismatches
        # update to latest kernel before instaling dependencies
        rhel.install_packages("kernel")
        node.reboot()

        if rhel.information.version.major == 7:
            # Add packages for rhel7
            rhel.install_packages(["libmnl-devel", "libbpf-devel"])

        try:
            rhel.install_packages("kernel-devel-$(uname -r)")
        except MissingPackagesException:
            node.log.debug("kernel-devel-$(uname -r) not found. Trying kernel-devel")
            rhel.install_packages("kernel-devel")

        # RHEL 8 doesn't require special cases for installed packages.
        # TODO: RHEL9 may require updates upon release

        rhel.group_install_packages("Development Tools")
        rhel.group_install_packages("Infiniband Support")
        rhel.install_packages(self._fedora_packages)

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

        node.execute(
            "pip3 install --upgrade meson",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to update Meson to latest version with pip3"
            ),
        )
        # after upgrade meson
        # if meson is in /usr/local/bin, link it
        # if meson is in /usr/bin, do nothing, upgrade will overwrite it
        if node.shell.exists(node.get_pure_path("/usr/local/bin/meson")):
            node.tools[Rm].remove_file("/usr/bin/meson", sudo=True)
            node.execute(
                "ln -fs /usr/local/bin/meson /usr/bin/meson",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Failed to link new meson version as the default "
                    "version in /usr/bin"
                ),
            )

        # NOTE: finding latest ninja is a pain,
        # so just fetch latest from github here
        git_tool = self.node.tools[Git]
        git_tool.clone(
            self._ninja_url,
            cwd=node.working_path,
        )
        node.execute(
            "./configure.py --bootstrap",
            cwd=node.get_pure_path(f"{node.working_path}/ninja"),
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to run ./configure.py --bootstrap"
            ),
        )
        node.tools[Mv].move(
            f"{node.working_path}/ninja/ninja",
            "/usr/bin/ninja",
            overwrite=True,
            sudo=True,
        )

        node.execute(
            "pip3 install --upgrade pyelftools",
            sudo=True,
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
        hotplug_match = self._search_hotplug_regex.finditer(after_rescind)
        matches_list = list(hotplug_match)
        if not list(matches_list):
            hotplug_alt_match = self._search_hotplug_regex_alt.finditer(after_rescind)
            if hotplug_alt_match:
                matches_list = list(hotplug_alt_match)
            else:
                command_dumped = "timeout: the monitored command dumped core"
                if command_dumped in self._last_run_output:
                    raise LisaException("Testpmd crashed after device removal.")

        # pick the last match

        if len(matches_list) > 0:
            last_match = matches_list[-1]
        else:
            raise LisaException(
                "Found no vf hotplug events in testpmd output. "
                "Check output to verify if PPS drop occurred and port removal "
                "event message matches the expected forms."
            )

        self.node.log.info(f"Identified hotplug event: {last_match.group(0)}")

        before_reenable = after_rescind[: last_match.start()]
        after_reenable = after_rescind[last_match.end() :]
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


def _discard_first_and_last_sample(data: List[int]) -> List[int]:
    # NOTE: first and last sample can be unreliable after switch messages
    # We're sampling for an order-of-magnitude difference so it
    # can mess up the average since we're using an unweighted mean

    # discard first and last sample so long as there are enough to
    # practically, we expect there to be > 20 unless rescind
    # performance is hugely improved in the cloud
    if len(data) < 3:
        return data
    else:
        return data[1:-1]


def _mean(data: List[int]) -> int:
    return sum(data) // len(data)
