# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePath, PurePosixPath
from typing import Any, List, Tuple, Type, Union

from assertpy import assert_that, fail
from semver import VersionInfo

from lisa.executable import ExecutableResult, Tool
from lisa.nic import NicInfo
from lisa.operating_system import Debian, Fedora, Suse, Ubuntu
from lisa.tools import (
    Echo,
    Git,
    KernelConfig,
    Kill,
    Lscpu,
    Lspci,
    Meson,
    Modprobe,
    Ninja,
    Pidof,
    Pip,
    Pkgconfig,
    Python,
    Timeout,
    Wget,
)
from lisa.util import LisaException, SkippedException, UnsupportedDistroException
from lisa.util.constants import DEVICE_TYPE_SRIOV, SIGINT
from microsoft.testsuites.dpdk.common import (
    DependencyInstaller,
    Downloader,
    GitDownloader,
    Installer,
    OsPackageDependencies,
    PackageManagerInstall,
    TarDownloader,
    get_debian_backport_repo_args,
    is_url_for_git_repo,
    is_url_for_tarball,
    unsupported_os_thrower,
)

PACKAGE_MANAGER_SOURCE = "package_manager"


# declare package dependencies for package manager DPDK installation
DPDK_PACKAGE_MANAGER_PACKAGES = DependencyInstaller(
    requirements=[
        # install linux-modules-extra-azure if it's available for mana_ib
        # older debian kernels won't have mana_ib packaged,
        # so skip the check on those kernels.
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Debian)
            and bool(x.get_kernel_information().version >= "5.15.0")
            and x.is_package_in_repo("linux-modules-extra-azure"),
            packages=["linux-modules-extra-azure"],
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Debian),
            packages=["dpdk", "dpdk-dev"],
            stop_on_match=True,
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Suse)
            and float(x.information.release) == 15.5,
            packages=["dpdk22", "dpdk22-devel"],
            stop_on_match=True,
        ),
        OsPackageDependencies(
            # alma/rocky have started
            # including testpmd by default in 'dpdk'
            matcher=lambda x: isinstance(x, Fedora)
            and not x.is_package_in_repo("dpdk-devel"),
            packages=["dpdk"],
            stop_on_match=True,
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, (Fedora, Suse)),
            packages=["dpdk", "dpdk-devel"],
            stop_on_match=True,
        ),
        OsPackageDependencies(matcher=unsupported_os_thrower),
    ]
)
# declare package/tool dependencies for DPDK source installation
DPDK_SOURCE_INSTALL_PACKAGES = DependencyInstaller(
    requirements=[
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Ubuntu)
            and x.information.codename == "bionic",
            packages=[
                "build-essential",
                "libmnl-dev",
                "libelf-dev",
                "libnuma-dev",
                "dpkg-dev",
                "pkg-config",
                "python3-pip",
                "python3-pyelftools",
                "python-pyelftools",
                # 18.04 doesn't need linux-modules-extra-azure
                # since it will never have MANA support
            ],
            stop_on_match=True,
        ),
        # install linux-modules-extra-azure if it's available for mana_ib
        # older debian kernels won't have mana_ib packaged,
        # so skip the check on those kernels.
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Debian)
            and bool(x.get_kernel_information().version >= "5.15.0")
            and x.is_package_in_repo("linux-modules-extra-azure"),
            packages=["linux-modules-extra-azure"],
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Debian),
            packages=[
                "build-essential",
                "libnuma-dev",
                "libmnl-dev",
                "python3-pyelftools",
                "libelf-dev",
                "pkg-config",
            ],
            stop_on_match=True,
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, Suse),
            packages=[
                "psmisc",
                "libnuma-devel",
                "numactl",
                "libmnl-devel meson",
                "gcc-c++",
            ],
            stop_on_match=True,
        ),
        OsPackageDependencies(
            matcher=lambda x: isinstance(x, (Fedora)),
            packages=[
                "psmisc",
                "numactl-devel",
                "pkgconfig",
                "elfutils-libelf-devel",
                "python3-pip",
                "kernel-modules-extra",
                "kernel-headers",
                "gcc-c++",
            ],
            stop_on_match=True,
        ),
        OsPackageDependencies(matcher=unsupported_os_thrower),
    ]
)


class DpdkPackageManagerInstall(PackageManagerInstall):
    def _setup_node(self) -> None:
        if isinstance(self._os, Debian):
            self._package_manager_extra_args = get_debian_backport_repo_args(self._os)

        elif isinstance(self._os, Fedora):
            self._os.install_epel()

    def get_installed_version(self) -> VersionInfo:
        return self._os.get_package_information("dpdk", use_cached=False)

    def _check_if_installed(self) -> bool:
        return self._os.package_exists("dpdk")


# implement SourceInstall for DPDK
class DpdkSourceInstall(Installer):
    _sample_applications = [
        "l3fwd",
        "multi_process/client_server_mp/mp_server",
        "multi_process/client_server_mp/mp_client",
    ]

    def _check_if_installed(self) -> bool:
        try:
            package_manager_install = self._os.package_exists("dpdk")
            # _get_installed_version for source install throws
            # if package is not found. So we don't need the result,
            # if the function doesn't throw, the version was found.
            _ = self.get_installed_version()
            # this becomes '(not package manager installed) and
            #                _get_installed_version() doesn't throw'
            return not package_manager_install
        except AssertionError:
            # _get_installed_version threw an AssertionError
            # so PkgConfig info was not found
            return False

    def _setup_node(self) -> None:
        if isinstance(self._os, Debian):
            self._package_manager_extra_args = get_debian_backport_repo_args(self._os)
            if isinstance(self._os, Ubuntu) and self._os.information.version < "22.4.0":
                self._os.update_packages("linux-azure")
                self._node.reboot()
        # install( Tool ) doesn't seem to install the tool until it's used :\
        # which breaks when another tool checks for it's existence before building...
        # like cmake, meson, make, autoconf, etc.
        self._node.tools[Ninja].install()
        self._node.tools[Pip].install_packages("pyelftools")

    def _uninstall(self) -> None:
        # undo source installation (thanks ninja)
        if not self._check_if_installed():
            return
        self._node.tools[Ninja].run(
            "uninstall", shell=True, sudo=True, cwd=self.dpdk_build_path
        )
        source_path = str(self._asset_path)
        working_path = str(self._node.get_working_path())
        assert_that(str(source_path)).described_as(
            "DPDK Installer source path was empty during attempted cleanup!"
        ).is_not_empty()
        assert_that(str(source_path)).described_as(
            "DPDK Installer source path was set to root dir "
            "'/' during attempted cleanup!"
        ).is_not_equal_to("/")
        assert_that(str(source_path)).described_as(
            f"DPDK Installer source path {source_path} was set to "
            f"working path '{working_path}' during attempted cleanup!"
        ).is_not_equal_to(working_path)
        # remove source code directory
        self._node.execute(f"rm -rf {str(source_path)}", shell=True)

    def get_installed_version(self) -> VersionInfo:
        return self._node.tools[Pkgconfig].get_package_version(
            "libdpdk", update_cached=True
        )

    def _install(self) -> None:
        super()._install()
        if self._sample_applications:
            sample_apps = f"-Dexamples={','.join(self._sample_applications)}"
        else:
            sample_apps = ""
        node = self._node
        # save the pythonpath for later
        python_path = node.tools[Python].get_python_path()
        self.dpdk_build_path = node.tools[Meson].setup(
            args=sample_apps, build_dir="build", cwd=self._asset_path
        )
        node.tools[Ninja].run(
            cwd=self.dpdk_build_path,
            timeout=1800,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "ninja build for dpdk failed. check build spew for missing headers "
                "or dependencies. Also check that this ninja version requirement "
                "has not changed for dpdk."
            ),
        )
        # using sudo and pip modules can get weird on some distros,
        # whether you install with pip3 --user or not.
        # to work around, add the user python path to sudo one
        node.tools[Ninja].run(
            "install",
            cwd=self.dpdk_build_path,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "ninja install failed for dpdk binaries."
            ),
            update_envs={"PYTHONPATH": f"$PYTHONPATH:{python_path}"},
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
        node.tools[Echo].write_to_file(
            ";".join(library_bashrc_lines),
            node.get_pure_path("$HOME/.bashrc"),
            append=True,
        )


class DpdkGitDownloader(GitDownloader):
    # DPDK git specific configuration setup
    # checkout latest tag if none was set
    def download(self) -> PurePath:
        super().download()
        if not self._git_ref:
            git = self._node.tools[Git]
            self._git_ref = git.get_tag(
                self._asset_path, filter_=r"^v.*"  # starts w 'v'
            )
            git.checkout(self._git_ref, cwd=self._asset_path)
        return self._asset_path


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
    _dpdk_lib_name = "libdpdk"

    @property
    def command(self) -> str:
        if not self._testpmd_install_path:
            return "testpmd"
        return self._testpmd_install_path

    _ubuntu_packages_1804 = [
        "build-essential",
        "libmnl-dev",
        "libelf-dev",
        "meson",
        "libnuma-dev",
        "dpkg-dev",
        "pkg-config",
        "python3-pip",
        "python3-pyelftools",
        "python-pyelftools",
        # 18.04 doesn't need linux-modules-extra-azure
        # since it will never have MANA support
    ]

    _ubuntu_packages_2004 = [
        "build-essential",
        "libnuma-dev",
        "libmnl-dev",
        "meson",
        "ninja-build",
        "python3-pyelftools",
        "libelf-dev",
        "pkg-config",
    ]

    # these are the same at the moment but might need tweaking later
    _debian_packages = _ubuntu_packages_2004

    _fedora_packages = [
        "psmisc",
        "numactl-devel",
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
        "libmnl-devel meson",
        "gcc-c++",
    ]
    _rte_target = "x86_64-native-linuxapp-gcc"

    _tx_pps_key = "transmit-packets-per-second"
    _rx_pps_key = "receive-packets-per-second"

    _testpmd_output_regex = {
        _tx_pps_key: r"Tx-pps:\s+([0-9]+)",
        _rx_pps_key: r"Rx-pps:\s+([0-9]+)",
    }
    _source_build_dest_dir = "/usr/local/bin"

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
        self.node.log.debug(f"Found DPDK version {str(self._dpdk_version_info)}.")
        return self._dpdk_version_info

    def has_dpdk_version(self) -> bool:
        return bool(self._dpdk_version_info > "0.0.0")

    def has_tx_ip_flag(self) -> bool:
        if not self.has_dpdk_version():
            fail(
                "Test suite bug: dpdk version was not set prior "
                "to querying the version information."
            )

        # black doesn't like to direct return VersionInfo comparison
        return bool(self.get_dpdk_version() >= "19.11.0")

    def use_package_manager_install(self) -> bool:
        assert_that(hasattr(self, "_dpdk_source")).described_as(
            "_dpdk_source was not set in DpdkTestpmd instance. "
            "set_dpdk_source must be called before instantiation."
        ).is_true()
        if self._dpdk_source == PACKAGE_MANAGER_SOURCE:
            return True
        else:
            return False

    def generate_testpmd_include(
        self, node_nic: NicInfo, vdev_id: int, force_netvsc: bool = False
    ) -> str:
        # handle generating different flags for pmds/device combos for testpmd

        # MANA and mlnx both don't require these arguments if all VFs are in use.
        # We have a primary nic to exclude in our tests, so we include the
        # test nic by either bus address and mac (MANA)
        # or by interface name (mlnx failsafe)
        #
        # include flag changed to 'allowlist' in 20.11
        # use 'allow' instead of 'deny' for envionments where
        # there is 1 shared bus address (MANA)
        # NOTE: I keep running into weird special cases of this.
        # 21.11 on ubuntu has -a even though 20.11+ shouldn't...
        help_output = self.node.execute(
            f"{self.command} --help", no_debug_log=True, no_info_log=True
        )
        allow_flag = "-a, --allow" in (help_output.stderr + help_output.stdout)
        if allow_flag:
            include_flag = "-a"
        else:
            include_flag = "-w"

        include_flag = f' {include_flag} "{node_nic.pci_slot}"'

        # build pmd argument
        if self.has_dpdk_version() and self.get_dpdk_version() < "18.11.0":
            pmd_name = "net_failsafe"
            pmd_flags = f"dev({node_nic.pci_slot}),dev(iface={node_nic.name},force=1)"
        elif self.is_mana:
            # mana selects by mac, just return the vdev info directly
            if node_nic.module_name == "uio_hv_generic" or force_netvsc:
                return f' --vdev="{node_nic.pci_slot},mac={node_nic.mac_addr}" '
            # if mana_ib is present, use mana friendly args
            elif self.node.tools[Modprobe].module_exists("mana_ib"):
                return (
                    f' --vdev="net_vdev_netvsc0,mac={node_nic.mac_addr}"'
                    f' --vdev="{node_nic.pci_slot},mac={node_nic.mac_addr}" '
                )
            else:
                # use eth interface for failsafe otherwise
                # test will probably fail due to low throughput
                pmd_name = "net_vdev_netvsc"
                pmd_flags = f"iface={node_nic.name}"
                # reset include flag for MANA since there is only one interface
                include_flag = ""
        else:
            # mlnx setup for failsafe
            pmd_name = "net_vdev_netvsc"
            pmd_flags = f"iface={node_nic.name},force=1"
        if node_nic.module_name == "hv_netvsc":
            # primary/upper/master nic is bound to hv_netvsc
            # when using net_failsafe implicitly or explicitly.
            # Set up net_failsafe/net_vdev_netvsc args here
            return f'--vdev="{pmd_name}{vdev_id},{pmd_flags}" ' + include_flag
        elif node_nic.module_name == "uio_hv_generic":
            # if using netvsc pmd, just let -w or -a select
            # which device to use. No other args are needed.
            return include_flag
        else:
            # if we're all the way through and haven't picked a pmd, something
            # has gone wrong. fail fast
            raise LisaException(
                (
                    f"Unknown driver({node_nic.module_name}) bound to "
                    f"{node_nic.name}/{node_nic.lower}."
                    "Cannot generate testpmd include arguments."
                )
            )

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

        # pick amount of queues for tx/rx (txq/rxq flag)
        # our tests use equal amounts for rx and tx
        if multiple_queues:
            if self.is_mana:
                queues = 8
            else:
                queues = 4
        else:
            queues = 1

        # MANA needs a file descriptor argument, mlnx doesn't.
        txd = 128

        # generate the flags for which devices to include in the tests
        nic_include_info = self.generate_testpmd_include(nic_to_include, vdev_id)

        # infer core count to assign based on number of queues
        cores_available = self.node.tools[Lscpu].get_core_count()
        assert_that(cores_available).described_as(
            "DPDK tests need more than 4 cores, recommended more than 8 cores"
        ).is_greater_than(4)

        queues_and_servicing_core = queues + service_cores

        while queues_and_servicing_core > (cores_available - 2):
            # if less, split the number of queues
            queues = queues // 2
            queues_and_servicing_core = queues + service_cores
            txd = 64  # txd has to be >= 64 for MANA.
            assert_that(queues).described_as(
                "txq value must be greater than 1"
            ).is_greater_than_or_equal_to(1)

        # label core index for future use
        max_core_index = queues_and_servicing_core

        # service cores excluded from forwarding cores count
        forwarding_cores = max_core_index - service_cores

        # core range argument
        core_list = f"-l 1-{max_core_index}"
        if extra_args:
            extra_args = extra_args.strip()
        else:
            extra_args = ""
        # mana pmd needs tx/rx descriptors declared.
        if self.is_mana:
            extra_args += f" --txd={txd} --rxd={txd}  --stats 2"
        if queues > 1:
            extra_args += f" --txq={queues} --rxq={queues}"

        assert_that(forwarding_cores).described_as(
            ("DPDK tests need at least one forwading core. ")
        ).is_greater_than(0)
        assert_that(max_core_index).described_as(
            "Test needs at least 1 core for servicing and one core for forwarding"
        ).is_greater_than(0)
        assert_that(self._testpmd_install_path).described_as(
            "Testpmd install path was not set, this indicates a logic"
            " error in the DPDK installation process."
        ).is_not_empty()
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

    def get_example_app_path(self, app_name: str) -> PurePath:
        if isinstance(self.installer, DpdkSourceInstall):
            return self.installer.dpdk_build_path.joinpath("examples").joinpath(
                app_name
            )
        else:
            raise AssertionError(
                "get_example_app_path called for DPDK package manager installation! "
                f"Trying to find {app_name} when DPDK was not built from source."
            )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._dpdk_source = kwargs.pop("dpdk_source", PACKAGE_MANAGER_SOURCE)
        self._dpdk_branch = kwargs.pop("dpdk_branch", "main")
        self._sample_apps_to_build = kwargs.pop("sample_apps", [])
        self._dpdk_version_info = VersionInfo(0, 0)
        self._testpmd_install_path: str = ""
        self._expected_install_path = ""
        self._determine_network_hardware()
        if self.use_package_manager_install():
            self.installer: Installer = DpdkPackageManagerInstall(
                self.node, DPDK_PACKAGE_MANAGER_PACKAGES
            )
        # if not package manager, choose source installation
        else:
            self._dpdk_repo_path_name = "dpdk"
            self._expected_install_path = self._source_build_dest_dir

            work_path = self.node.get_working_path_with_required_space(5)
            self.current_work_path = self.node.get_pure_path(work_path)
            self.dpdk_path = self.node.get_pure_path(work_path).joinpath(
                self._dpdk_repo_path_name
            )
            if is_url_for_git_repo(self._dpdk_source):
                downloader: Downloader = DpdkGitDownloader(
                    node=self.node,
                    git_repo=self._dpdk_source,
                    git_ref=self._dpdk_branch,
                )

            elif is_url_for_tarball(self._dpdk_source):
                downloader = TarDownloader(node=self.node, tar_url=self._dpdk_source)
            else:
                raise LisaException(
                    "URL provided for dpdk source did not validate as "
                    f"a tarball or git repo. Found {self._dpdk_source} "
                    " Expected https://___/___.git or /path/to/tar.tar[.gz] or "
                    "https://__/__.tar[.gz]"
                )
            self.installer = DpdkSourceInstall(
                node=self.node,
                os_dependencies=DPDK_SOURCE_INSTALL_PACKAGES,
                downloader=downloader,
            )
        # if dpdk is already installed, find the binary and check the version
        if self.find_testpmd_binary(assert_on_fail=False):
            pkgconfig = self.node.tools[Pkgconfig]
            if pkgconfig.package_info_exists(self._dpdk_lib_name):
                self._dpdk_version_info = pkgconfig.get_package_version(
                    self._dpdk_lib_name
                )

    def _determine_network_hardware(self) -> None:
        lspci = self.node.tools[Lspci]
        device_list = lspci.get_devices_by_type(DEVICE_TYPE_SRIOV)
        self.is_connect_x3 = any(
            ["ConnectX-3" in dev.device_info for dev in device_list]
        )
        self.is_mana = any(["Microsoft" in dev.vendor for dev in device_list])

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
        node = self.node
        if not isinstance(node.os, (Debian, Fedora, Suse)):
            return False
        if isinstance(node.os, Ubuntu) and node.os.information.codename == "bionic":
            # bionic needs to update to latest first
            node.os.update_packages("")
        if self.is_mana and not (
            isinstance(node.os, Ubuntu) or isinstance(node.os, Fedora)
        ):
            raise SkippedException("MANA DPDK test is not supported on this OS")

        self.installer.do_installation()
        self._dpdk_version_info = self.installer.get_installed_version()
        self._load_drivers_for_dpdk()
        self.find_testpmd_binary(check_path=self._expected_install_path)
        return True

    def _load_drivers_for_dpdk(self) -> None:
        self.node.log.info("Loading drivers for infiniband, rdma, and mellanox hw...")
        if self.is_connect_x3:
            network_drivers = ["mlx4_core", "mlx4_ib"]
        elif self.is_mana:
            network_drivers = []
            mana_builtin = self.node.tools[KernelConfig].is_built_in(
                "CONFIG_MICROSOFT_MANA"
            )
            if not mana_builtin:
                network_drivers += ["mana"]
            mana_ib_builtin = self.node.tools[KernelConfig].is_built_in(
                "CONFIG_MANA_INFINIBAND"
            )
            if not mana_ib_builtin:
                network_drivers.append("mana_ib")
        else:
            network_drivers = ["mlx5_core", "mlx5_ib"]
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
                if network_drivers:
                    self.node.execute(
                        (
                            "dracut --add-drivers "
                            f"'{' '.join(network_drivers)} ib_uverbs' -f"
                        ),
                        expected_exit_code=0,
                        expected_exit_code_failure_message=(
                            "Issue loading mlx and ib_uverb drivers into ramdisk."
                        ),
                        sudo=True,
                    )
        else:
            raise UnsupportedDistroException(self.node.os)
        if self.is_mana:
            # MANA has less special casing required (for now anyway)
            rdma_drivers = ["ib_uverbs"]
        else:
            rdma_drivers = ["ib_core", "ib_uverbs", "rdma_ucm"]

            # some versions of dpdk require these two, some don't.
            # some systems have them, some don't. Load if they're there.
            for module in ["ib_ipoib", "ib_umad"]:
                if modprobe.module_exists(module):
                    rdma_drivers.append(module)

        modprobe.load(rdma_drivers)
        if network_drivers:
            modprobe.load(network_drivers)

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
