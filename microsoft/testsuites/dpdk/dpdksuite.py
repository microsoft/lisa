# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import itertools
from typing import Dict, List

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features import Sriov
from lisa.features.network_interface import NetworkInterface
from lisa.testsuite import simple_requirement
from lisa.tools import Echo, Lspci, Mount
from microsoft.testsuites.dpdk.dpdktestpmd import DpdkTestpmd


@TestSuiteMetadata(
    area="dpdk",
    category="functional",
    description="""
    This test suite check DPDK functionality
    """,
)
class Dpdk(TestSuite):
    @TestCaseMetadata(
        description="""
            This test case checks DPDK can be built and installed correctly.
            Prerequisites, accelerated networking must be enabled.
            The VM should have at least two network interfaces,
             with one interface for management.
            More detailes refer https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk#prerequisites # noqa: E501
        """,
        requirement=simple_requirement(
            min_nic_count=2,
            network_interface=Sriov,
        ),
        priority=1,
    )
    def check_dpdk_build(self, node: Node, log: Logger) -> None:
        network_interface_feature = node.features[NetworkInterface]
        sriov_is_enabled = network_interface_feature.is_enabled_sriov()
        log.info(f"Verify SRIOV is enabled: {sriov_is_enabled}")
        assert_that(sriov_is_enabled).described_as(
            "SRIOV was not enabled for this test node."
        ).is_true()

        # dump some info about the pci devices before we start
        lspci = node.tools[Lspci]
        log.info(f"LSPCI Info:\n{lspci.run().stdout}\n")

        # enable hugepages (required by dpdk)
        self._hugepages_init(node)
        self._hugepages_enable(node, log)

        # initialize testpmd tool (installs dpdk)
        testpmd = DpdkTestpmd(node)
        testpmd.install()

        # initialize node nic info class (gathers info about nic devices)
        node_nic_info = NodeNicInfo(node)
        assert_that(len(node_nic_info)).described_as(
            "Test needs at least 2 NICs on the test node."
        ).is_greater_than_or_equal_to(2)
        log.info(node_nic_info)

        # grab a nic and run testpmd
        test_nic = node_nic_info.get_nic(node_nic_info.get_upper_nics()[-1])
        vdev_type = "net_vdev_netvsc0"
        testpmd_include_str = test_nic.testpmd_include(vdev_type)
        testpmd_output = testpmd.run_with_timeout(testpmd_include_str, 30)
        tx_pps = testpmd.get_tx_pps_from_testpmd_output(testpmd_output)
        log.info(
            f"TX-PPS:{tx_pps} from {test_nic._upper}/{test_nic._lower}:"
            + f"{test_nic._pci_slot}"
        )
        assert_that(tx_pps).described_as(
            f"TX-PPS ({tx_pps}) should have been greater than 2^20 (~1m) PPS."
        ).is_greater_than(2 ** 20)

    def _execute_expect_zero(self, node: Node, cmd: str) -> str:
        result = node.execute(cmd, sudo=True, shell=True)
        result.assert_exit_code()
        return result.stdout

    def _hugepages_init(self, node: Node) -> None:
        mount = node.tools[Mount]
        mount.mount(disk_name="nodev", point="/mnt/huge", type="hugetlbfs")
        mount.mount(
            disk_name="nodev",
            point="/mnt/huge-1G",
            type="hugetlbfs",
            options="pagesize=1G",
        )

    def _hugepages_enable(self, node: Node, log: Logger) -> None:
        echo = node.tools[Echo]
        echo.write_to_file(
            "1024",
            "/sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages",
            sudo=True,
        )
        echo.write_to_file(
            "1",
            "/sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages",
            sudo=True,
        )


class NicInfo:

    # Class for info about an single upper/lower nic pair.
    # devices using SRIOV on azure typically have an upper synthetic device
    # paired with a lower SRIOV Virtual Function (VF) device that
    # enables the passthrough to the physical NIC.

    def __init__(self, upper: str, lower: str = "", pci_slot: str = "") -> None:
        self._has_secondary = lower != "" or pci_slot == ""
        self._upper = upper
        self._lower = lower
        self._pci_slot = pci_slot

    def has_secondary(self) -> bool:
        return self._has_secondary

    def __str__(self) -> str:
        return (
            "NicInfo:\n"
            f"upper: {self._upper}\n"
            f"lower: {self._lower}\n"
            f"pci_slot: {self._pci_slot}\n"
        )

    def testpmd_include(self, vdev_type: str) -> str:
        assert_that(self._has_secondary).is_true().described_as(
            (
                f"This interface {self._upper} does not have a lower interface "
                "and pci slot associated with it. Aborting."
            )
        )
        return f'--vdev="{vdev_type},iface={self._upper}" --allow "{self._pci_slot}"'


class NodeNicInfo:

    # Class for all of the nics on a node. Contains multiple NodeNic classes.
    # Init identifies upper/lower paired devices and the pci slot info for the lower.

    def _get_nic_names(self, node: Node) -> List[str]:
        # identify all of the nics on the device, excluding tunnels and loopbacks etc.
        result = node.execute(
            " ls /sys/class/net/ | grep -Ev $(ls /sys/devices/virtual/net)",
            shell=True,
            sudo=True,
        )
        nic_names = result.stdout.splitlines()
        for item in nic_names:
            assert_that(item).described_as(
                "nic name could not be found"
            ).is_not_equal_to("")
        return nic_names

    def _get_nic_device(self, node: Node, nic_name: str) -> str:
        slot_info_result = node.execute(f"readlink /sys/class/net/{nic_name}/device")
        slot_info_result.assert_exit_code()
        base_device_result = node.execute(f"basename {slot_info_result.stdout}")
        base_device_result.assert_exit_code()
        # todo check addr matches expectation
        return base_device_result.stdout

    def _get_node_nic_info(self, node: Node, nic_list: List[str]) -> None:
        # Identify which nics are slaved to master devices.
        # This should be really simple with /usr/bin/ip but experience shows
        # the tool isn't super consistent across distros in this regard

        # use sysfs to gather upper/lower nic pairings and pci slot info
        for pairing in itertools.permutations(nic_list, 2):
            upper_nic, lower_nic = pairing
            # check a nic pairing to identify upper/lower relationship
            upper_check = node.execute(
                f"readlink /sys/class/net/{lower_nic}/upper_{upper_nic}"
            )
            if upper_check.exit_code == 0:
                assert_that(upper_check.stdout).is_not_equal_to("")
                pci_slot = self._get_nic_device(node, lower_nic)
                assert_that(pci_slot).is_not_empty()
                # check pcislot info looks correct
                nic_info = NicInfo(upper_nic, lower_nic, pci_slot)
                self.append(nic_info)

        # identify nics which don't have a pairing (non-AN devices)
        for nic in nic_list:
            if not self.nic_info_is_present(nic):
                self.append(NicInfo(nic))

        assert_that(self.is_empty()).is_false()

    def _get_default_nic(self, node: Node, nic_list: List[str]) -> str:
        cmd = "ip route | grep default | awk '{print $5}'"
        default_interface = node.execute(cmd)
        assert_that(default_interface.exit_code).is_zero()
        assert_that(len(default_interface.stdout)).is_greater_than(0)
        default_interface_name = default_interface.stdout.strip()
        assert_that(default_interface_name in nic_list).described_as(
            (
                f"ERROR: NIC name found as default {default_interface_name} "
                f"was not in original list of nics {nic_list}."
            )
        ).is_true()
        return default_interface_name

    def __init__(self, node: Node):
        self._nics: Dict[str, NicInfo] = dict()
        nics = self._get_nic_names(node)
        self._get_node_nic_info(node, nics)

    def append(self, next_node: NicInfo) -> None:
        self._nics[next_node._upper] = next_node

    def is_empty(self) -> bool:
        return len(self._nics) == 0

    def __len__(self) -> int:
        return len(self._nics)

    def get_unpaired_devices(self) -> List[str]:
        return [x._upper for x in self._nics.values() if not x.has_secondary()]

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
            _str += f"{self._nics[nic]}"
        return _str
