# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import ipaddress
import itertools
import re
import threading
from typing import Dict, List, Tuple

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features import NetworkInterface, Sriov
from lisa.testsuite import simple_requirement
from lisa.tools import Echo, Lspci, Mount
from microsoft.testsuites.dpdk.dpdktestpmd import DpdkTestpmd

vdev_type = "net_vdev_netvsc0"


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
        priority=2,
        requirement=simple_requirement(
            min_nic_count=2,
            network_interface=Sriov,
        ),
    )
    def check_dpdk_build(self, node: Node, log: Logger) -> None:
        # setup and unwrap the resources for this test
        test_kit = initialize_node_resources(node, log)
        node_nic_info, testpmd = test_kit.node_nic_info, test_kit.testpmd

        # grab a nic and run testpmd
        test_nic = node_nic_info.get_nic(node_nic_info.get_upper_nics()[-1])

        testpmd_include_str = test_nic.testpmd_include(vdev_type)
        testpmd_cmd = testpmd._generate_testpmd_command(testpmd_include_str, "txonly")
        testpmd_output = testpmd.run_for_n_seconds(testpmd_cmd, 10)
        tx_pps = testpmd.get_tx_pps_from_testpmd_output(testpmd_output)
        log.info(
            f"TX-PPS:{tx_pps} from {test_nic._upper}/{test_nic._lower}:"
            + f"{test_nic._pci_slot}"
        )
        assert_that(tx_pps).described_as(
            f"TX-PPS ({tx_pps}) should have been greater than 2^20 (~1m) PPS."
        ).is_greater_than(2 ** 20)

    @TestCaseMetadata(
        description="""
            Tests a more realistic sender/forwarder/receiver setup.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=2,
            network_interface=Sriov,
            min_count=3,
        ),
    )
    def check_3node_forwarding(self, environment: Environment, log: Logger) -> None:
        test_kits = _init_nodes_concurrent(environment, log)
        for item in test_kits:
            # use these to quiet flake up
            log.info(f"found node info: {item.node_nic_info}")
        sender, forwarder, receiver = test_kits

        snd_nic, fwd_nic, rcv_nic = [x.node_nic_info.get_nic("eth1") for x in test_kits]

        forwarder.testpmd._reconfigure_forwarding(rcv_nic._ip_addr)

        """ snd_inc, fwd_inc, rcv_inc = [
            x.testpmd_include(vdev_type) for x in [snd_nic, fwd_nic, rcv_nic]
        ]

        # TODO: forwarder needs macfwd.c code edited to allow forwarding to receiver
        snd_cmd = sender.testpmd._generate_testpmd_command(
            snd_inc,
            "txonly",
            extra_args=f"--tx-ip={snd_nic._ip_addr},{fwd_nic._ip_addr}",
        )
        fwd_cmd = forwarder.testpmd._generate_testpmd_command(fwd_inc, "mac")

        rcv_cmd = receiver.testpmd._generate_testpmd_command(rcv_inc, "rxonly")

        kit_cmd_pairs = {
            sender: snd_cmd,
            forwarder: fwd_cmd,
            receiver: rcv_cmd,
        }
        testpmd_outputs = _run_testpmd_concurrent(kit_cmd_pairs, log)

        log.info(f"receiver: {testpmd_outputs[receiver]}")
        log.info(f"sender: {testpmd_outputs[sender]}")
        log.info(f"forwarder: {testpmd_outputs[forwarder]}") """

        # TODO: rest of test in future commit.


def _init_hugepages(node: Node) -> None:
    mount = node.tools[Mount]
    mount.mount(disk_name="nodev", point="/mnt/huge", type="hugetlbfs")
    mount.mount(
        disk_name="nodev",
        point="/mnt/huge-1G",
        type="hugetlbfs",
        options="pagesize=1G",
    )
    _enable_hugepages(node)


def _enable_hugepages(node: Node) -> None:
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

    def __init__(
        self,
        upper: str,
        lower: str = "",
        pci_slot: str = "",
    ) -> None:
        self._has_secondary = lower != "" or pci_slot == ""
        self._upper = upper
        self._lower = lower
        self._pci_slot = pci_slot
        self._ip_addr = ""
        self._mac_addr = ""

    def has_secondary(self) -> bool:
        return self._has_secondary

    def __str__(self) -> str:
        return (
            "NicInfo:\n"
            f"upper: {self._upper}\n"
            f"lower: {self._lower}\n"
            f"pci_slot: {self._pci_slot}\n"
            f"ip_addr: {self._ip_addr}\n"
            f"mac_addr: {self._mac_addr}\n"
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
        cmd = "/sbin/ip route | grep default | awk '{print $5}'"
        default_interface = node.execute(cmd, shell=True, sudo=True)
        default_interface.assert_exit_code()
        assert_that(len(default_interface.stdout)).is_greater_than(0)
        default_interface_name = default_interface.stdout.strip()
        assert_that(default_interface_name in nic_list).described_as(
            (
                f"ERROR: NIC name found as default {default_interface_name} "
                f"was not in original list of nics {nic_list}."
            )
        ).is_true()
        return default_interface_name

    def _get_host_if_info(self, node: Node) -> None:
        # for parsing ip addr show (ipv4)
        _ip_regex = (
            r"inet\s+([0-9a-fA-F]{1,3}\.[0-9a-fA-F]{1,3}\."
            r"[0-9a-fA-F]{1,3}\.[0-9a-fA-F]{1,3})"
        )
        _mac_regex = (
            r"ether\s+([0-9a-fA-F]{2}:[0-9a-fA-F]{1,3}:"
            r"[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:"
            r"[0-9a-fA-F]{2}:[0-9a-fA-F]{2})"
        )

        for nic in self.get_upper_nics():
            # get ip and mac
            result = node.execute(f"/sbin/ip addr show {nic}", shell=True)
            result.assert_exit_code()
            ip_match = re.search(_ip_regex, result.stdout)
            mac_match = re.search(_mac_regex, result.stdout)

            if ip_match and mac_match:
                # check we found matches for both
                for match in [ip_match, mac_match]:
                    assert_that(len(match.groups())).described_as(
                        (
                            f"(IP) Trouble parsing `ip addr show {nic}` output."
                            " Number of match groups was unexpected."
                        )
                    ).is_equal_to(1)

                ip_addr = ip_match.group(1)
                mac_addr = mac_match.group(1)

                # double check IP address looks right
                try:
                    ipaddress.ip_address(ip_addr)
                except ValueError:
                    assert_that(False).described_as(
                        f"{ip_addr} was not recognized as an IP Address."
                    ).is_true()

                # save them both off
                self.get_nic(nic)._ip_addr = ip_addr
                self.get_nic(nic)._mac_addr = mac_addr
            else:
                assert_that(False).described_as(
                    f"Could not parse output of ip addr show {nic}"
                ).is_true()

    def __init__(self, node: Node):
        self._nics: Dict[str, NicInfo] = dict()
        nics = self._get_nic_names(node)
        self._get_node_nic_info(node, nics)
        default_nic = self._get_default_nic(node, nics)
        awk_cmd = "awk '{print $2}'"
        self.ip_addr = node.execute(
            f"/sbin/ip addr show {default_nic} | grep inet | {awk_cmd}"
        ).stdout.strip()
        self._get_host_if_info(node)

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


class NodeResources:
    def __init__(
        self, _node: Node, _node_nic_info: NodeNicInfo, _testpmd: DpdkTestpmd
    ) -> None:
        self.node_nic_info = _node_nic_info
        self.testpmd = _testpmd
        self.node = _node


def initialize_node_resources(node: Node, log: Logger) -> NodeResources:
    network_interface_feature = node.features[NetworkInterface]
    sriov_is_enabled = network_interface_feature.is_enabled_sriov()
    log.info(f"Node[{node.name}] Verify SRIOV is enabled: {sriov_is_enabled}")
    assert_that(sriov_is_enabled).described_as(
        f"SRIOV was not enabled for this test node ({node.name})"
    ).is_true()

    # dump some info about the pci devices before we start
    lspci = node.tools[Lspci]
    log.info(f"Node[{node.name}] LSPCI Info:\n{lspci.run().stdout}\n")
    # init and enable hugepages (required by dpdk)
    _init_hugepages(node)

    # initialize testpmd tool (installs dpdk)
    testpmd = DpdkTestpmd(node)
    testpmd.install()

    # initialize node nic info class (gathers info about nic devices)
    node_nic_info = NodeNicInfo(node)
    assert_that(len(node_nic_info)).described_as(
        "Test needs at least 2 NICs on the test node."
    ).is_greater_than_or_equal_to(2)
    return NodeResources(node, node_nic_info, testpmd)


def _threaded_resource_init(
    node: Node, log: Logger, output: List[NodeResources]
) -> None:
    # threading.Thread target function, results aggregated into output list
    output.append(initialize_node_resources(node, log))


def _threaded_testpmd(
    node_cmd_pair: Tuple[NodeResources, str],
    log: Logger,
    output: Dict[NodeResources, str],
) -> None:
    testkit, cmd = node_cmd_pair
    output[testkit] = testkit.testpmd.run_for_n_seconds(cmd, 10)


def _run_testpmd_concurrent(
    node_cmd_pairs: Dict[NodeResources, str], log: Logger
) -> Dict[NodeResources, str]:
    output: Dict[NodeResources, str] = dict()
    threads: List[threading.Thread] = []
    for pair in node_cmd_pairs.items():
        threads.append(
            threading.Thread(target=_threaded_testpmd, args=(pair, log, output))
        )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return output


def _init_nodes_concurrent(
    environment: Environment, log: Logger
) -> List[NodeResources]:
    # Use threading module to parallelize the IO-bound node init.
    test_kits: List[NodeResources] = []
    threads: List[threading.Thread] = []
    for node in environment.nodes.list():
        thread = threading.Thread(
            target=_threaded_resource_init, args=((node, log, test_kits))
        )
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    return test_kits
