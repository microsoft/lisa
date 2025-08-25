# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Dict, List, cast

from assertpy import assert_that
from retry import retry

from lisa import Environment, Node, RemoteNode, constants
from lisa.features import NetworkInterface
from lisa.nic import NicInfo
from lisa.operating_system import BSD
from lisa.tools import Dhclient, Ip, IpInfo, Kill, Lspci, Ping, Ssh


@retry(exceptions=AssertionError, tries=30, delay=2)  # type:ignore
def initialize_nic_info(
    environment: Environment, is_sriov: bool = True
) -> Dict[str, Dict[str, NicInfo]]:
    vm_nics: Dict[str, Dict[str, NicInfo]] = {}
    for node in environment.nodes.list():
        network_interface_feature = node.features[NetworkInterface]
        interfaces_info_list: List[
            IpInfo
        ] = network_interface_feature.get_all_primary_nics_ip_info()
        if is_sriov:
            sriov_count = network_interface_feature.get_nic_count()
            assert_that(sriov_count).described_as(
                f"there is no sriov nic attached to VM {node.name}"
            ).is_greater_than(0)
        nics_info = node.nics
        nics_info.reload()
        found_ip = False
        for interface_info in interfaces_info_list:
            # for some old distro, need run dhclient to get ip address for extra nics
            found_ip = False
            for node_nic in nics_info.nics.values():
                if interface_info.mac_addr == node_nic.mac_addr:
                    if not node_nic.ip_addr:
                        node.tools[Ip].up(node_nic.name)
                        node.tools[Dhclient].renew(node_nic.name)
                        node_nic.ip_addr = node.tools[Ip].get_ip_address(node_nic.name)
                    if interface_info.ip_addr != node_nic.ip_addr:
                        assert_that(node_nic.ip_addr).described_as(
                            f"This interface {node_nic} ip {node_nic.ip_addr} is not "
                            f"equal to ip from nic {interface_info.ip_addr} from "
                            "network interface."
                        ).is_equal_to(interface_info.ip_addr)
                    found_ip = True
                    break
            assert_that(found_ip).described_as(
                f"This interface name {interface_info.nic_name} with mac: "
                f"{interface_info.mac_addr} does not have a IP address "
                f"inside vm, it should equal to {interface_info.ip_addr}."
            ).is_true()
        if is_sriov:
            assert_that(len(nics_info.get_device_slots())).described_as(
                f"VF count inside VM is {len(set(nics_info.get_device_slots()))},"
                f"actual sriov nic count is {sriov_count}"
            ).is_equal_to(sriov_count)
        vm_nics[node.name] = nics_info.nics

    return vm_nics


@retry(exceptions=AssertionError, tries=150, delay=2)  # type:ignore
def sriov_basic_test(environment: Environment) -> None:
    for node in environment.nodes.list():
        # 1. Check VF counts listed from lspci is expected.
        lspci = node.tools[Lspci]
        devices_slots = lspci.get_device_names_by_type(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        if len(devices_slots) != len(set(node.nics.get_device_slots())):
            node.nics.reload()
        assert_that(devices_slots).described_as(
            "count of sriov devices listed from lspci is not expected,"
            " please check the driver works properly"
        ).is_length(len(set(node.nics.get_device_slots())))

        # 2. Check module of sriov network device is loaded.
        for module_name in node.nics.get_used_modules(["hv_netvsc"]):
            if node.nics.is_module_reloadable(module_name):
                assert_that(node.nics.module_exists(module_name)).described_as(
                    "The module of sriov network device isn't loaded."
                ).is_true()


def sriov_vf_connection_test(
    environment: Environment,
    vm_nics: Dict[str, Dict[str, NicInfo]],
    turn_off_lower: bool = False,
    remove_module: bool = False,
) -> None:
    source_node = cast(RemoteNode, environment.nodes[0])
    dest_node = cast(RemoteNode, environment.nodes[1])
    source_ssh = source_node.tools[Ssh]
    dest_ssh = dest_node.tools[Ssh]

    # enable public key for ssh connection
    dest_ssh.enable_public_key(source_ssh.generate_key_pairs())

    # generate 200Mb file
    source_node.execute("dd if=/dev/urandom of=large_file bs=1M count=200")

    # for each nic on source node, find the same subnet nic on dest node, then copy
    # 200Mb file
    max_retry_times = 10
    for _, source_nic_info in vm_nics[source_node.name].items():
        matched_dest_nic_name = ""

        # find the same subnet nic on dest node
        for dest_nic_name, dest_nic_info in vm_nics[dest_node.name].items():
            # only when IPs are in the same subnet, IP1 of machine A can connect to
            # IP2 of machine B
            # e.g. eth2 IP is 10.0.2.3 on machine A, eth2 IP is 10.0.3.4 on machine
            # B, use nic name doesn't work in this situation
            if (
                dest_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
                == source_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
            ):
                matched_dest_nic_name = dest_nic_name
                break
        assert_that(matched_dest_nic_name).described_as(
            f"can't find the same subnet nic with {source_nic_info.ip_addr} on"
            f" machine {source_node.name}, please check network setting of "
            f"machine {dest_node.name}."
        ).is_not_empty()

        # set source and dest network info
        dest_nic_info = vm_nics[dest_node.name][matched_dest_nic_name]
        dest_ip = vm_nics[dest_node.name][matched_dest_nic_name].ip_addr
        source_ip = source_nic_info.ip_addr
        source_synthetic_nic = source_nic_info.name
        dest_synthetic_nic = dest_nic_info.name
        source_nic = source_pci_nic = source_nic_info.pci_device_name
        dest_nic = dest_pci_nic = dest_nic_info.pci_device_name

        # if remove_module is True, use synthetic nic to copy file
        if remove_module or turn_off_lower or isinstance(source_node.os, BSD):
            # For FreeBSD, packets are logged on the vsc interface
            source_nic = source_synthetic_nic
            dest_nic = dest_synthetic_nic

        # turn off lower device
        if turn_off_lower:
            if source_nic_info.lower:
                source_node.tools[Ip].down(source_pci_nic)
            if dest_nic_info.lower:
                dest_node.tools[Ip].down(dest_pci_nic)

        # get origin tx_packets and rx_packets before copy file
        source_tx_packets_origin = source_node.nics.get_packets(source_nic)
        dest_tx_packets_origin = dest_node.nics.get_packets(dest_nic, "rx_packets")

        # check the connectivity between source and dest machine using ping
        for _ in range(max_retry_times):
            ping_result = source_node.tools[Ping].ping(
                target=dest_ip, nic_name=source_synthetic_nic, count=1, sudo=True
            )
            if ping_result:
                break
        assert ping_result, (
            f"fail to ping {dest_ip} from {source_node.name} to "
            f"{dest_node.name} after retry {max_retry_times}"
        )

        # copy 200 Mb file from source ip to dest ip
        source_node.execute(
            f"scp -o BindAddress={source_ip} -i $HOME/.ssh/id_rsa -o"
            f" StrictHostKeyChecking=no large_file "
            f"$USER@{dest_ip}:/tmp/large_file",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Fail to copy file large_file from"
            f" {source_ip} to {dest_ip}",
        )

        # get tx_packets and rx_packets after copy file
        source_tx_packets = source_node.nics.get_packets(source_nic)
        dest_tx_packets = dest_node.nics.get_packets(dest_nic, "rx_packets")

        # verify tx_packets value of source nic is increased after coping 200Mb file
        #  from source to dest
        assert_that(
            int(source_tx_packets), "insufficient TX packets sent"
        ).is_greater_than(int(source_tx_packets_origin))

        # verify rx_packets value of dest nic is increased after receiving 200Mb
        #  file from source to dest
        assert_that(
            int(dest_tx_packets), "insufficient RX packets received"
        ).is_greater_than(int(dest_tx_packets_origin))

        # turn on lower device, if turned off before
        if turn_off_lower:
            if source_nic_info.lower:
                source_node.tools[Ip].up(source_pci_nic)
            if dest_nic_info.lower:
                dest_node.tools[Ip].up(dest_pci_nic)


def cleanup_iperf3(environment: Environment) -> None:
    for node in environment.nodes.list():
        kill = node.tools[Kill]
        kill.by_name("iperf3")


def sriov_disable_enable(environment: Environment, times: int = 4) -> None:
    initialize_nic_info(environment)
    sriov_basic_test(environment)
    node = cast(RemoteNode, environment.nodes[0])
    network_interface_feature = node.features[NetworkInterface]
    for _ in range(times):
        sriov_is_enabled = network_interface_feature.is_enabled_sriov()
        network_interface_feature.switch_sriov(enable=not sriov_is_enabled)
    sriov_is_enabled = network_interface_feature.is_enabled_sriov()
    if not sriov_is_enabled:
        network_interface_feature.switch_sriov(enable=True)
    sriov_basic_test(environment)


def remove_extra_nics_per_node(node: Node) -> None:
    node = cast(RemoteNode, node)
    network_interface_feature = node.features[NetworkInterface]
    network_interface_feature.remove_extra_nics()


def remove_extra_nics(environment: Environment) -> None:
    for node in environment.nodes.list():
        remove_extra_nics_per_node(node)


def restore_extra_nics_per_node(node: Node) -> None:
    remove_extra_nics_per_node(node)
    network_interface_feature = node.features[NetworkInterface]
    network_interface_feature.attach_nics(
        network_interface_feature.origin_extra_sriov_nics_count,
        enable_accelerated_networking=True,
    )
    network_interface_feature.attach_nics(
        network_interface_feature.origin_extra_synthetic_nics_count,
        enable_accelerated_networking=False,
    )


def restore_extra_nics(environment: Environment) -> None:
    # restore nics info into previous status
    for node in environment.nodes.list():
        restore_extra_nics_per_node(node)


def disable_enable_devices(environment: Environment) -> None:
    for node in environment.nodes.list():
        lspci = node.tools[Lspci]
        lspci.disable_devices_by_type(constants.DEVICE_TYPE_SRIOV)
        lspci.enable_devices()


def reload_modules(environment: Environment) -> bool:
    reload_modules = False
    for node in environment.nodes.list():
        for module_name in node.nics.get_used_modules(["hv_netvsc"]):
            if node.nics.is_module_reloadable(module_name):
                node.nics.unload_module(module_name)
                node.nics.load_module(module_name)
                reload_modules = True
    return reload_modules
