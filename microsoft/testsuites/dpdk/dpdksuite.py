# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath

from assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features import Sriov
from lisa.testsuite import simple_requirement
from lisa.operating_system import Ubuntu, Redhat, CentOs
from lisa.tools import Git, Wget
from lisa.util import SkippedException
from typing import List, Dict
import itertools


class NicInfo:
    def __init__(self, upper: str, lower: str = "", pci_slot: str = "") -> None:
        self._has_secondary = lower != "" or pci_slot == ""
        self._upper = upper
        self._lower = lower
        self._pci_slot = pci_slot

    def has_secondary(self) -> bool:
        return self._has_secondary

    def __str__(self) -> str:
        return f"""
NicInfo:
upper: {self._upper}
lower: {self._lower}
pci_slot: {self._pci_slot}
        """

    def testpmd_include(self, vdev_type: str) -> str:
        assert_that(self._has_secondary).is_true().described_as(
            f"This interface {self._upper} does not have a lower interface and pci slot associated with it. Aborting."
        )
        return f'--vdev="{vdev_type},iface={self._upper}" --allow "{self._pci_slot}"'


class NodeNicInfo:
    _nics: Dict[str, NicInfo] = dict()

    def __init__(self, initializer: List[NicInfo] = []):
        for nic in initializer:
            self._nics[nic._upper] = nic

    def append(self, next_node: NicInfo) -> None:
        self._nics[next_node._upper] = next_node

    def IsEmpty(self) -> bool:
        return len(self._nics) == 0

    def __len__(self) -> int:
        return len(self._nics)

    def get_upper_nics(self) -> List[str]:
        return [self._nics[x]._upper for x in self._nics.keys()]

    def get_lower_nics(self) -> List[str]:
        return [self._nics[x]._lower for x in self._nics.keys()]

    def get_device_slots(self) -> List[str]:
        return [self._nics[x]._pci_slot for x in self._nics.keys()]

    def get_nic(self, nic_name: str) -> NicInfo:
        return self._nics[nic_name]

    def nic_info_is_present(self, nic_name: str) -> bool:
        return nic_name in self.get_upper_nics() or nic_name in self.get_lower_nics()

    def __str__(self) -> str:
        _str = ""
        for nic in self._nics:
            _str += f"{nic}"
        return _str


@TestSuiteMetadata(
    area="dpdk",
    category="functional",
    description="""
    This test suite check DPDK functionality
    """,
)
class dpdk(TestSuite):
    @TestCaseMetadata(
        description="""
            This test case checks DPDK can be built and installed correctly.
        """,
        requirement=simple_requirement(
            supported_features=[Sriov],
        ),
        priority=1,
    )
    def check_dpdk_build(self, case_name: str, node: Node) -> None:

        sriov_feature = node.features[Sriov]
        sriov_is_enabled = sriov_feature.enabled()
        self.log.info(f"Verify SRIOV is enabled: {sriov_is_enabled}")
        assert_that(sriov_is_enabled).is_true().described_as(
            "SRIOV was not enabled for this test node."
        )
        self._install_dpdk_dependencies(node)
        self._hugepages_init(node)
        self._hugepages_enable(node)
        self._install_dpdk(node)
        nics = self._get_nic_names(node)
        node_nic_info = self._get_node_nic_info(node, nics)
        assert_that(len(node_nic_info)).described_as(
            "Test needs at least 2 NICs on the test node."
        ).is_greater_than_or_equal_to(2)
        test_nic = node_nic_info.get_nic(node_nic_info.get_upper_nics()[-1])
        vdev_type = "net_vdev_netvsc"
        self.log.info(
            f"/usr/local/bin/dpdk-testpmd -l 2,3 -n 4 --proc-type=primary {test_nic.testpmd_include(vdev_type)} -- --forward-mode=txonly -a"
        )
        timer_proc = node.execute_async(
            "sleep 30 && killall -s INT /usr/local/bin/dpdk-testpmd",
            sudo=True,
            shell=True,
        )
        testpmd_proc = node.execute_async(
            f"/usr/local/bin/dpdk-testpmd -l 2,3 -n 4 --proc-type=primary {test_nic.testpmd_include(vdev_type)} -- --forward-mode=txonly -a",
            sudo=True,
        )
        timer_proc.wait_result()
        proc_result = testpmd_proc.wait_result()
        self.log.info(proc_result.stdout)

    _ubuntu_packages = [
        "librdmacm-dev",
        "librdmacm1",
        "build-essential",
        "libnuma-dev",
        "libmnl-dev",
        "libelf-dev",
        "meson",
        "rdma-core",
        "librdmacm-dev",
        "librdmacm1",
        "build-essential",
        "libnuma-dev",
        "libmnl-dev",
        "libelf-dev",
        "dpkg-dev",
        "pkg-config",
        "python3-pip",
        "python3-pyelftools",
        "python-pyelftools",
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
    ]
    _rte_target = "x86_64-native-linuxapp-gcc"
    _dpdk_github = "https://github.com/DPDK/dpdk.git"
    _ninja_url = (
        "https://github.com/ninja-build/ninja/releases/download/v1.10.2/ninja-linux.zip"
    )

    _ip_addr_regex = r"[0-9]+:\s+([a-zA-Z0-9\-_]+):\s+<(?:[a-zA-Z0-9_]+,?)+>"

    def _install_dpdk_dependencies(self, node: Node) -> None:

        if isinstance(node.os, Ubuntu):
            for package in self._ubuntu_packages:
                node.os.install_packages(package)
            self.log.info("Packages installed for Ubunutu")
            self._execute_expect_zero(node, "pip3 install --upgrade meson")
            self._execute_expect_zero(node, "mv /usr/bin/meson /usr/bin/meson.bak")
            self._execute_expect_zero(node, "ln -s /usr/local/bin/meson /usr/bin/meson")
            self._execute_expect_zero(node, "pip3 install --upgrade ninja")
            self._execute_expect_zero(
                node, "modprobe -a rdma_cm rdma_ucm ib_core ib_uverbs mlx4_core mlx4_ib"
            )

        elif isinstance(node.os, Redhat) or isinstance(node.os, CentOs):
            self._execute_expect_zero(
                node, "yum update -y --disablerepo='*' --enablerepo='*microsoft*'"
            )
            node.os.install_packages(
                ["groupinstall", "'Infiniband Support'"], signed=False
            )  # todo gross hack to support groupinstall
            for package in self._redhat_packages:
                node.os.install_packages(package)
            result = node.execute(
                "dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f"
            )  # add mellanox drivers
            self.log.debug("\n".join([result.stdout, result.stderr]))
            self._execute_expect_zero(node, "systemctl enable rdma")
            self._execute_expect_zero(node, "pip3 install --upgrade meson")
            self._execute_expect_zero(node, "ln -s /usr/local/bin/meson /usr/bin/meson")

            wget_tool = node.tools[Wget]
            wget_tool.get(self._ninja_url)
            node.execute(f"mv ninja-linux.zip {node.working_path}/")
            self.log.info(node.execute("ls -la").stdout)
            self._execute_expect_zero(
                node, "unzip ninja-linux.zip && mv ninja /usr/bin/ninja"
            )
            self._execute_expect_zero(node, "pip3 install --upgrade pyelftools")
        else:
            raise SkippedException(
                f"SRIOV test is not implemented for target os: {node.os}"
            )

    def _execute_expect_zero_with_path(
        self, node: Node, cmd: str, path: PurePath
    ) -> str:
        self.log.info(f"RUNCMD: {cmd}")
        result = node.execute(cmd, sudo=True, cwd=path, shell=True)
        assert_that(result.exit_code).described_as(
            f"{cmd} failed with code {result.exit_code} and stdout+stderr:"
            + f"\n{result.stdout}\n=============\n{result.stderr}\n=============\n"
        ).is_zero()
        if len(result.stdout) > 1024:
            self.log.debug(
                f"NOTE: Truncating result since output is larger than 1024.\n{result.stdout[:512]}\n.......(content has been truncated).......\n{result.stdout[-512:]}"
            )
        else:
            self.log.debug(f"{cmd}:\n{result.stdout}")  # TODO: debug

        return result.stdout

    def _execute_expect_zero(self, node: Node, cmd: str) -> str:
        return self._execute_expect_zero_with_path(node, cmd, node.working_path)

    def _hugepages_init(self, node: Node) -> None:
        self._execute_expect_zero(node, "mkdir -p /mnt/huge")
        self._execute_expect_zero(node, "mkdir -p /mnt/huge-1G")
        self._execute_expect_zero(node, "mount -t hugetlbfs nodev /mnt/huge")
        self._execute_expect_zero(
            node, "mount -t hugetlbfs nodev /mnt/huge-1G -o 'pagesize=1G'"
        )
        result = node.execute("grep -i huge /proc/meminfo && ls /mnt/", shell=True)
        self.log.info(f"hugepages status \n{result.stdout}")

    def _hugepages_enable(self, node: Node) -> None:
        self._execute_expect_zero(
            node,
            "sh -c 'echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages'",
        )
        self._execute_expect_zero(
            node,
            "sh -c 'echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages'",
        )
        result = node.execute("grep -i huge /proc/meminfo && ls /mnt/", shell=True)
        self.log.info(f"hugepages status \n{result.stdout}")

    def _install_dpdk(self, node: Node) -> None:
        git_tool = node.tools[Git]
        git_tool.clone(self._dpdk_github, cwd=node.working_path)
        dpdk_path = node.working_path.joinpath("dpdk")
        self._execute_expect_zero_with_path(node, "meson build", dpdk_path)
        self.log.info(node.execute("ls -la", cwd=dpdk_path).stdout)
        dpdk_build_path = dpdk_path.joinpath("build")
        self._execute_expect_zero_with_path(node, "which ninja", dpdk_build_path)
        self._execute_expect_zero_with_path(node, "ninja", dpdk_build_path)
        self._execute_expect_zero_with_path(node, "ninja install", dpdk_build_path)
        self._execute_expect_zero_with_path(node, "ldconfig", dpdk_build_path)

    def _get_nic_names(self, node: Node) -> List[str]:
        result = node.execute(
            " ls /sys/class/net/ | grep -Ev $(ls /sys/devices/virtual/net)",
            shell=True,
            sudo=True,
        )
        nic_names = result.stdout.split("\r\n")
        for item in nic_names:
            assert_that(item).is_not_equal_to("").described_as(
                "nic name could not be found"
            )
        self.log.info(f"network devices: {nic_names}")
        return nic_names

    def _get_nic_device(self, node: Node, nic_name: str) -> str:
        nic_device = self._execute_expect_zero(
            node, f"readlink /sys/class/net/{nic_name}/device"
        )
        base_device_name = self._execute_expect_zero(node, f"basename {nic_device}")
        assert_that(base_device_name).is_not_equal_to("")
        return base_device_name

    def _get_node_nic_info(self, node: Node, nic_list: List[str]) -> NodeNicInfo:
        # Identify which nics are slaved to master devices.
        # This should be really simple with /usr/bin/ip but experience shows
        # some platforms are buggy and require another method
        nodeNics = NodeNicInfo()

        # use sysfs to gather upper/lower nic pairings and pci slot info
        for pairing in itertools.permutations(nic_list, 2):
            self.log.debug(f"Checking: {pairing}")
            upper_nic, lower_nic = pairing
            # check a nic pairing to identify upper/lower relationship
            upper_check = node.execute(
                f"readlink /sys/class/net/{lower_nic}/upper_{upper_nic}"
            )
            if upper_check.exit_code == 0:
                self.log.info(upper_check.stdout)
                assert_that(upper_check.stdout).is_not_equal_to("")
                address_check = node.execute(
                    f"readlink /sys/class/net/{lower_nic}/device"
                )
                pci_slot = address_check.stdout.split("/")[-1]
                assert_that(pci_slot).is_not_empty()
                # check pcislot info looks correct
                self.log.info(f"{lower_nic} : {pci_slot}")
                nic_info = NicInfo(upper_nic, lower_nic, pci_slot)
                nodeNics.append(nic_info)

        self.log.info(f"found primary->secondary nic pairings:\n{nodeNics}")
        # identify nics which don't have a pairing
        for nic in nic_list:
            if not nodeNics.nic_info_is_present(nic):
                self.log.info(f"Identified an unpaired interface: {nic}")
                nodeNics.append(NicInfo(nic))

        assert_that(nodeNics.IsEmpty()).is_false()
        return nodeNics

    def _get_default_nic(self, node: Node, nic_list: List[str]) -> str:
        cmd = "ip route | grep default | awk '{print $5}'"
        default_interface = self._execute_expect_zero(node, cmd)
        assert_that(len(default_interface)).is_greater_than(0)
        assert_that(default_interface in nic_list).is_true()
        return default_interface
