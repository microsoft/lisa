# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from math import ceil
from pathlib import PurePath, PurePosixPath
from typing import Any, List, Optional, Tuple, Type, Union

from assertpy import assert_that, fail
from semver import VersionInfo

from lisa.base_tools import Mv
from lisa.executable import ExecutableResult, Tool
from lisa.features import Disk
from lisa.nic import NicInfo
from lisa.operating_system import Debian, Fedora, Suse, Ubuntu, Redhat
from lisa.tools import (
    Cat,
    Chmod,
    Dmesg,
    Echo,
    Git,
    KernelConfig,
    Kill,
    Lscpu,
    Lsmod,
    Lspci,
    Modprobe,
    Pidof,
    Pkgconfig,
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
from lisa.util.constants import DEVICE_TYPE_SRIOV, SIGINT
from microsoft.testsuites.dpdk.common import (
    is_ubuntu_latest_or_prerelease,
    is_ubuntu_lts_version,
)
from microsoft.testsuites.dpdk.dpdk_vf_helper import DpdkVfHelper
from microsoft.testsuites.dpdk.rdma_core import RdmaCoreManager

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
    _dpdk_lib_name = "libdpdk"

    @property
    def command(self) -> str:
        if not self._testpmd_install_path:
            return "dpdk-testpmd"
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
        if self._dpdk_version_info and self._dpdk_version_info < "20.11.0":
            include_flag = "-w"
        else:
            include_flag = "-a"
        include_flag = f' {include_flag} "{node_nic.pci_slot}"'

        # build pmd argument
        if self.has_dpdk_version() and self.get_dpdk_version() < "18.11.0":
            pmd_name = "net_failsafe"
            pmd_flags = f"dev({node_nic.pci_slot}),dev(iface={node_nic.name},force=1)"
        elif self.vf_helper.is_mana():
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
            if self.vf_helper.is_mana():
                queues = 16
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

        # set log args and mana-specific options
        log_level_args = "--log-level netvsc,debug "
        if self.vf_helper.is_mana():
            # mana pmd needs tx/rx descriptors declared.
            extra_args += f" --txd={txd} --rxd={txd}  --stats 2"
            log_level_args += "--log-level mana,debug "
        if queues > 1:
            extra_args += f" --txq={queues} --rxq={queues}"

        assert_that(forwarding_cores).described_as(
            ("DPDK tests need at least one forwading core. ")
        ).is_greater_than(0)
        assert_that(max_core_index).described_as(
            "Test needs at least 1 core for servicing and one core for forwarding"
        ).is_greater_than(0)

        return (
            f"env LD_LIBRARY_PATH=/usr/local/lib64 "
            f"{self._testpmd_install_path} {core_list} "
            f"{nic_include_info} {log_level_args}"
            f" -- --forward-mode={mode} "
            f"-a --stats-period 2 --nb-cores={forwarding_cores} {extra_args} "
        )

    _mana_errors = [
        re.compile(
            r"mana [0-9a-fA-F]{4}:[0-9a-fA-F]{2}:"
            r"[0-9a-fA-F]{2}\.[0-9a-fA-F]{1,4}: "
            r"HWC: Failed hw_channel req"
        ),
    ]

    def check_for_driver_regressions(self) -> None:
        # check for known mana errors to catch regressions.
        dmesg = self.node.tools[Dmesg]
        driver_logs = dmesg.get_output(force_run=True)
        for error in self._mana_errors:
            found_error = error.search(driver_logs)
            if found_error:
                self.node.log.debug(driver_logs)
                raise LisaException(
                    "Found known MANA error in dmesg, indicates a regression "
                    f"or possible test bug: {found_error.group()}"
                )

    def run_for_n_seconds(self, cmd: str, timeout: int) -> str:
        self._last_run_timeout = timeout
        self.node.log.info(f"{self.node.name} running: {cmd}")

        proc_result = self.node.tools[Timeout].run_with_timeout(
            cmd, timeout, SIGINT, kill_timeout=timeout + 10
        )
        self._last_run_output = proc_result.stdout
        self.check_for_driver_regressions()
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
        self.check_for_driver_regressions()
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
        cast_to_ints = _trim_zeroes(cast_to_ints)
        return _discard_warmup_and_cooldown_samples(cast_to_ints)

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
            self._sample_apps_to_build += apps
        else:
            self._sample_apps_to_build = []

    def get_dpdk_portmask(self, ports: List[int]) -> str:
        # helper to take a list of DPDK port IDs and return
        # the bit mask the EAL uses to enable them.
        mask = 0
        for i in ports:
            mask |= 1 << i
        return hex(mask)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # do not update kernel on backporting
        self.update_kernel = kwargs.pop("update_kernel", True)
        # set source args for builds if needed, first for dpdk
        self.dpdk_build_path: Optional[PurePath] = None
        self._dpdk_source: str = kwargs.pop("dpdk_source", PACKAGE_MANAGER_SOURCE)
        self._dpdk_branch: str = kwargs.pop("dpdk_branch", "")
        # then for rdma-core
        rdma_core_source = kwargs.pop("rdma_core_source", "")
        rdma_core_ref = kwargs.pop("rdma_core_ref", "")
        self.rdma_core = RdmaCoreManager(
            node=self.node,
            rdma_core_source=rdma_core_source,
            rdma_core_ref=rdma_core_ref,
            update_kernel=self.update_kernel,
        )
        self._sample_apps_to_build = kwargs.pop("sample_apps", list())
        self._dpdk_version_info = VersionInfo(0, 0)
        self._testpmd_install_path: str = ""
        self._pkg_config_envs = {
            "PKG_CONFIG_PATH": "${PKG_CONFIG_PATH}:/usr/local/lib64/pkgconfig/",
            "LD_LIBRARY_PATH": "${LD_LIBRARY_PATH}:/usr/local/lib64/",
        }
        if not self.use_package_manager_install():
            self._dpdk_repo_path_name = "dpdk"
            work_path = self.node.get_working_path_with_required_space(20)
            if not work_path:
                self.node.features[Disk].add_data_disk(count=1, size_in_gb=100)
                work_path = self.node.get_working_path_with_required_space(20)
            assert work_path, "Could not find space to build DPDK"
            self.current_work_path = self.node.get_pure_path(work_path)
            self.dpdk_path = self.node.get_pure_path(work_path).joinpath(
                self._dpdk_repo_path_name
            )

        # signal whether to build the debug or release version
        self.is_perf_test = kwargs.pop("build_release", False)

        # determine network hardware and whether to enforce the strict
        # test threshold (based on user argument)
        enforce_hw_threshold = kwargs.pop("enforce_strict_threshold", False)

        self.vf_helper = DpdkVfHelper(
            should_enforce=enforce_hw_threshold, node=self.node
        )

        # if dpdk is already installed, find the binary and check the version
        if self.find_testpmd_binary(assert_on_fail=False) or \
           self.find_testpmd_binary(check_path='/usr/local/bin', assert_on_fail=False):
            pkgconfig = self.node.tools[Pkgconfig]
            if pkgconfig.package_info_exists(
                self._dpdk_lib_name,
                update_envs=self._pkg_config_envs,
            ):
                self._dpdk_version_info = pkgconfig.get_package_version(
                    self._dpdk_lib_name,
                    update_cached=True,
                    update_envs=self._pkg_config_envs,
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

    def _set_backport_repo_args(self) -> None:
        distro = self.node.os
        # skip attempting to use backports for latest/prerlease
        # and non-lts ubuntu versions
        if isinstance(distro, Ubuntu) and (
            is_ubuntu_latest_or_prerelease(distro) or not is_ubuntu_lts_version(distro)
        ):
            self._backport_repo_args = []
        # otherwise check if a backport repo exists use it if so
        elif isinstance(distro, Debian):
            repos = distro.get_repositories()
            backport_repo = f"{distro.information.codename}-backports"
            if any([backport_repo in repo.name for repo in repos]):
                self._backport_repo_args = [f"-t {backport_repo}"]
            else:
                self._backport_repo_args = []
        # otherwise assume backports are included in default repos
        # TODO: check for how RHEL and SUSE manage backports
        else:
            self._backport_repo_args = []

    def _fix_mirrorlist_to_vault(self, node) -> None:
        node.execute("""sed -i '
                    s/^mirrorlist=/#mirrorlist=/;
                    s/^#[ ]*baseurl=/baseurl=/;
                    /^baseurl=/ s/mirror/vault/;
                ' /etc/yum.repos.d/CentOS-*.repo""", shell=True, sudo=True)

    def _install(self) -> bool:
        self._testpmd_output_after_reenable = ""
        self._testpmd_output_before_rescind = ""
        self._testpmd_output_during_rescind = ""
        self._last_run_output = ""
        node = self.node
        distro = node.os
        if not (
            isinstance(distro, Fedora)
            or isinstance(distro, Debian)
            or isinstance(distro, Suse)
        ):
            raise SkippedException(
                UnsupportedDistroException(
                    distro, "DPDK tests not implemented for this OS."
                )
            )

        if isinstance(node.os, Redhat) and node.os.information.version < "8.0.0":
            self._fix_mirrorlist_to_vault(node)
            node.os.install_packages(["centos-release-scl"])

            # Fix CentOS-SCL's paths to mirrorlist
            self._fix_mirrorlist_to_vault(node)
            devtoolset_version = 8
            devtoolset_pkg = f"devtoolset-{devtoolset_version}"
            node.os.install_packages([devtoolset_pkg])
            links = {
                    "gcc": ("gcc", "cc"),
                    "g++": ("g++", "c++"),
            }
            for binary in [alias
                         for aliases in links.values()
                         for alias in aliases
                    ]:
                node.tools[Mv].move(f"/bin/{binary}", f"/bin/{binary}_back",
                        overwrite=True, sudo=True, ignore_error=None)
            devtoolset_binpath = f"/opt/rh/{devtoolset_pkg}/root/bin"
            for binary, aliases in links.items():
                for alias in aliases:
                    result = node.execute(
                        f"ln -s {devtoolset_binpath}/{binary} /bin/{alias}", sudo=True
                    )
                    result.assert_exit_code()

        # before doing anything: determine if backport repo needs to be enabled
        self._set_backport_repo_args()

        if self.has_dpdk_version():
            # DPDK is already installed
            node.log.info(
                "DPDK was installed from source previously, using existing DPDK."
            )
            self._load_drivers_for_dpdk()
            return True

        # if this is mana VM, we don't support other distros yet
        is_mana_test_supported = isinstance(distro, Ubuntu) or isinstance(
            distro, Fedora
        )
        if self.vf_helper.is_mana() and not is_mana_test_supported:
            raise SkippedException("MANA DPDK test is not supported on this OS")

        # if we need an rdma-core source install, do it now.
        if self.rdma_core.can_install_from_source() or (
            is_mana_test_supported and self.vf_helper.is_mana()
        ):
            # ensure no older version is installed
            distro.uninstall_packages("rdma-core")
            self.rdma_core.do_source_install()

        # otherwise, install kernel and dpdk deps from package manager, git, or tar
        self._install_dependencies()
        # install any missing rdma-core packages
        rdma_packages = self.rdma_core.get_missing_distro_packages()
        distro.install_packages(rdma_packages)

        # installing from distro package manager
        if self.use_package_manager_install():
            self.node.log.info(
                "Installing dpdk and dev package from package manager..."
            )
            if isinstance(distro, Debian):
                distro.install_packages(
                    ["dpdk", "dpdk-dev"],
                    extra_args=self._backport_repo_args,
                )
            elif isinstance(distro, (Fedora, Suse)):
                distro.install_packages(["dpdk", "dpdk-devel"])
            else:
                raise NotImplementedError(
                    "Dpdk package names are missing in dpdktestpmd.install"
                    f" for os {distro.name}"
                )
            self.node.log.info(
                f"Installed DPDK version {str(self._dpdk_version_info)} "
                "from package manager"
            )

            self._dpdk_version_info = distro.get_package_information("dpdk")
            self.find_testpmd_binary()
            self._load_drivers_for_dpdk()
            return True
        else:
            if (
                isinstance(distro, Debian)
                or isinstance(distro, (Fedora, Suse))
            ):
                # if not using package manager and dpdk is already installed, uninstall it
                # in preperation for source build
                if distro.package_exists("dpdk"):
                    distro.uninstall_packages("dpdk")
            else:
                raise NotImplementedError(
                    "Dpdk package names are missing in dpdktestpmd.install"
                    f" for os {distro.name}"
                )

        # otherwise install from source tarball or git
        self.node.log.info(f"Installing dpdk from source: {self._dpdk_source}")

        if self.find_testpmd_binary(
            assert_on_fail=False, check_path="/usr/local/bin"
        ):  # tools are already installed
            # version info must already be set from __init__
            return True
        if self.node.shell.exists(self.node.get_pure_path("/DPDK_BUILD_BY_LISA")):
            self.node.log
        git_tool = node.tools[Git]
        echo_tool = node.tools[Echo]

        if self._dpdk_source and self._dpdk_source.endswith(".tar.gz"):
            wget_tool = node.tools[Wget]
            tar_tool = node.tools[Tar]
            node.tools[Chmod]
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
        else:
            git_tool.clone(
                self._dpdk_source,
                cwd=self.current_work_path,
                dir_name=self._dpdk_repo_path_name,
                ref=self._dpdk_branch.strip(),
            )
            if not self._dpdk_branch:
                # dpdk stopped using a default branch
                # if a branch is not specified, get latest version tag.
                self._dpdk_branch = git_tool.get_tag(
                    self.dpdk_path, filter_=r"^v.*"  # starts w 'v'
                )

                git_tool.checkout(self._dpdk_branch, cwd=self.dpdk_path)

        self._load_drivers_for_dpdk()

        # add sample apps to compilation if they are present
        if self._sample_apps_to_build:
            build_flags = [f"-Dexamples={','.join(self._sample_apps_to_build)}"]
        else:
            build_flags = [""]

        if self.is_perf_test:
            build_flags += ["-Dbuildtype=release"]
        else:
            build_flags += ["-Dbuildtype=debugoptimized"]

        # build specific drivers to avoid building entire DPDK project
        drivers_to_build = (
            "*/mlx*,bus/vmbus,"
            "net/*netvsc,net/ring,net/virtio,net/bonding,"
            "bus/auxiliary,common/*"
        )
        # add mana driver to build if needed
        if self.vf_helper.is_mana():
            drivers_to_build += ",net/mana"

        # shrink build, if supported
        cat = node.tools[Cat]
        meson_options_content = cat.run("meson_options.txt",
                cwd=self.dpdk_path, shell=True).stdout
        if "enable_drivers" in meson_options_content:
            build_flags += [
                f"-Denable_drivers={drivers_to_build}"
            ]

        if "enable_apps" in meson_options_content:
            build_flags += [
                "-Denable_apps=app/test-pmd"
            ]

        node.execute(
            f"meson setup {' '.join(build_flags)} build",
            shell=True,
            cwd=self.dpdk_path,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "meson build for dpdk failed, check that"
                "dpdk build has not changed to eliminate the use of meson or "
                "meson version is compatible with this dpdk version and OS."
            ),
            no_debug_log=True,
            no_info_log=True,
        )
        self.dpdk_build_path = self.dpdk_path.joinpath("build")
        node.log.debug(f"Building DPDK in dir: {self.dpdk_build_path}")
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
            no_debug_log=True,
            no_info_log=True,
        )
        node.execute(
            "ninja install",
            cwd=self.dpdk_build_path,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "ninja install failed for dpdk binaries."
            ),
            no_debug_log=True,
            no_info_log=True,
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
        self._dpdk_version_info = self.node.tools[Pkgconfig].get_package_version(
            self._dpdk_lib_name, update_cached=True, update_envs=self._pkg_config_envs
        )
        self.node.tools[Echo].write_to_file(
            value=",".join([self._dpdk_source, self._dpdk_branch]),
            file=self.node.get_pure_path("/DPDK_BUILD_BY_LISA"),
            sudo=True,
        )

        # try to copy over the sample apps as well.
        if self._sample_apps_to_build:
            example_path = self.dpdk_build_path.joinpath("examples")
            self.node.execute(
                f"cp {str(example_path)}/* /usr/local/bin/", shell=True, sudo=True
            )
            self.node.execute(f"ls -la /usr/local/bin/*", shell=True, sudo=True)
        return True

    def _load_drivers_for_dpdk(self) -> None:
        self.node.log.info("Loading drivers for infiniband, rdma, and mellanox hw...")
        if self.vf_helper.is_connect_x3():
            network_drivers = ["mlx4_core", "mlx4_ib"]
        elif self.vf_helper.is_mana():
            network_drivers = []
            if not self.node.tools[Lsmod].module_exists("mana_ib"):
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
        elif self.update_kernel and isinstance(self.node.os, Debian):
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
            if not self.vf_helper.is_connect_x3():
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

        if self.vf_helper.is_mana():
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

    def _install_dependencies(self) -> None:
        node = self.node
        if isinstance(node.os, Ubuntu):
            self._install_ubuntu_dependencies()
        elif isinstance(node.os, Debian):
            node.os.install_packages(
                self._debian_packages, extra_args=self._backport_repo_args
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
                self._install_ninja_meson_and_pyelftools()

    def _install_ubuntu_dependencies(self) -> None:
        node = self.node
        ubuntu = node.os
        if not isinstance(ubuntu, Ubuntu):
            fail(
                "_install_ubuntu_dependencies was called on node "
                f"which was not Ubuntu: {node.os.information.full_version}"
            )
            return  # appease the type checker

        # apply update to latest first
        if self.update_kernel:
            ubuntu.update_packages("linux-azure")
            node.reboot()
        if ubuntu.information.version < "18.4.0":
            raise SkippedException(
                f"Ubuntu {str(ubuntu.information.version)} is not supported. "
                "Minimum documented version for DPDK support is >=18.04"
            )
        elif ubuntu.information.version < "20.4.0":
            ubuntu.install_packages(
                self._ubuntu_packages_1804,
                extra_args=self._backport_repo_args,
            )
            if not self.use_package_manager_install():
                self._install_ninja_meson_and_pyelftools()
        else:
            ubuntu.install_packages(
                self._ubuntu_packages_2004,
                extra_args=self._backport_repo_args,
            )
            # MANA tests use linux-modules-extra-azure, install if it's available.
            if self.update_kernel and self.vf_helper.is_mana() and \
                    ubuntu.is_package_in_repo("linux-modules-extra-azure"):
                ubuntu.install_packages("linux-modules-extra-azure")

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
        # update to latest kernel before installing dependencies
        if self.update_kernel:
            rhel.install_packages(["kernel", "kernel-modules-extra", "kernel-headers"])
            node.reboot()
            try:
                rhel.install_packages("kernel-devel")
            except MissingPackagesException:
                node.log.debug("Fedora: kernel-devel not found, attempting to continue")

        if rhel.information.version.major == 7:
            # Add packages for rhel7
            rhel.install_packages(["libmnl-devel", "libbpf-devel"])

        # RHEL 8 doesn't require special cases for installed packages.
        # TODO: RHEL9 may require updates upon release
        if not self.rdma_core.is_installed_from_source:
            rhel.group_install_packages("Infiniband Support")

        rhel.group_install_packages("Development Tools")
        rhel.install_packages(self._fedora_packages)
        rhel.uninstall_packages(["doxygen"])

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
            # ninja from git has been flaky. try pkg install first
            for pkg in ["ninja-build", "meson", "python3-pyelftools"]:
                try:
                    rhel.install_packages(pkg)
                except LisaException:
                    continue
            self._install_ninja_meson_and_pyelftools()

    def _install_ninja_meson_and_pyelftools(self) -> None:
        node = self.node
        ninja_available = node.execute("command -v ninja", shell=True).exit_code == 0
        meson_available = node.execute("command -v meson", shell=True).exit_code == 0
        if not ninja_available:
            self._install_ninja()
        if not meson_available:
            self._install_meson()
        self._install_pyelftools()

    def _install_pyelftools(self) -> None:
        node = self.node
        node.execute(
            "pip3 install --upgrade pyelftools",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not upgrade pyelftools with pip3."
            ),
        )

    def _install_ninja(self) -> None:
        # NOTE: finding latest ninja is a pain,
        # so just fetch latest from github here
        node = self.node
        git_tool = node.tools[Git]
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

    def _install_meson(self) -> None:
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
            result = node.execute(f"which {bin_name}", shell=True, sudo=True)
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
def _trim_zeroes(data: List[int]) -> List[int]:
    # NOTE: we occasionally get a 0 for the first pps result sample,
    # it's annoying to factor it into the average when
    # there are only like 10 samples so discard any
    # leading and trailing 0's if they're present.

    # confirm data is not all zero
    all_zeroes = all([x == 0 for x in data])
    if all_zeroes:
        return data

    # leading:
    for i in range(len(data)):
        if data[i] != 0:
            data = data[i:]
            break
    # trailing (same but reverse the list)
    data = data[::-1]
    for i in range(len(data)):
        if data[i] != 0:
            data = data[i:]
            break

    return data[::-1]


def _discard_warmup_and_cooldown_samples(data: List[int]) -> List[int]:
    # NOTE: first and last sample can be unreliable after switch messages
    # We're sampling for an order-of-magnitude difference so it
    # can mess up the average since we're using a straight mean.
    if len(data) < 5:
        return data
    else:
        # count the samples in the dataset
        samples = len(data)
        # plan to discard 25% to avoid cooldown and warmup junk
        discard = ceil(samples * 0.125)
        # return the trimmed dataset
        return data[discard:-discard]


def _mean(data: List[int]) -> int:
    return sum(data) // len(data)
