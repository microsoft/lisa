# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Dict, List, cast

from assertpy import assert_that
from retry import retry

from lisa import Environment, Node, RemoteNode, constants
from lisa.features import NetworkInterface
from lisa.nic import NicInfo
from lisa.operating_system import BSD
from lisa.tools import Dhclient, Ip, IpInfo, Kill, Lspci, Ssh


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
                f"VF count inside VM is {len(set(nics_info.get_device_slots()))}, "
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


def _validate_and_skip_nic(nic_info: NicInfo, nic_name: str, node: RemoteNode) -> bool:
    """Validate NIC and return True if it should be skipped."""
    # Skip InfiniBand interfaces as they use RDMA, not standard Ethernet
    if nic_info.name and nic_info.name.startswith("ib"):
        node.log.debug(f"Skipping InfiniBand interface {nic_info.name} on {node.name}")
        return True

    # Skip enslaved VF NICs (they don't have IP addresses in Azure)
    # In Azure Accelerated Networking, VFs are enslaved to synthetic NICs
    # Traffic through synthetic NIC automatically uses VF for acceleration
    if nic_info.pci_device_name and not nic_info.ip_addr:
        node.log.debug(
            f"Skipping enslaved VF {nic_name} on {node.name} "
            f"(has PCI device but no IP)"
        )
        return True

    # For NICs that should participate in testing, validate required fields
    assert_that(nic_info.name).described_as(
        f"NIC {nic_name} on {node.name} is missing name. " f"NIC info: {nic_info}"
    ).is_not_none()

    # Only NICs with IP addresses can be tested for connectivity
    assert_that(nic_info.ip_addr).described_as(
        f"NIC {nic_name} on {node.name} is missing IP address but wasn't skipped. "
        f"This indicates an unexpected NIC configuration. "
        f"NIC info: {nic_info}"
    ).is_not_none()

    return False


def _test_file_transferring(
    source_node: RemoteNode,
    dest_node: RemoteNode,
    source_ip: str,
    dest_ip: str,
    source_nic: str,
    dest_nic: str,
    source_synthetic_nic: str,
    max_retry_times: int = 10,
) -> None:
    """Perform ping and file transfer test between NICs."""

    # Create test file for transfer (200MB)
    source_node.execute("dd if=/dev/urandom of=large_file bs=1M count=200")

    # get origin tx_packets and rx_packets before copy file
    source_tx_packets_origin = source_node.nics.get_packets(source_nic)
    dest_tx_packets_origin = dest_node.nics.get_packets(dest_nic, "rx_packets")

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
    assert_that(int(source_tx_packets), "insufficient TX packets sent").is_greater_than(
        int(source_tx_packets_origin)
    )

    # verify rx_packets value of dest nic is increased after receiving 200Mb
    #  file from source to dest
    assert_that(
        int(dest_tx_packets), "insufficient RX packets received"
    ).is_greater_than(int(dest_tx_packets_origin))

    # Clean up the test file after transfer
    source_node.execute("rm -f large_file", shell=True)
    dest_node.execute("rm -f /tmp/large_file", shell=True)


def _find_matching_dest_nic(
    source_nic_info: NicInfo,
    vm_nics: Dict[str, Dict[str, NicInfo]],
    dest_node: RemoteNode,
) -> tuple[str, int]:
    """Find destination NIC on same subnet as source.
    Returns (nic_name, skipped_count)."""
    skipped_infiniband = 0

    for dest_nic_name, dest_nic_info in vm_nics[dest_node.name].items():
        if _validate_and_skip_nic(dest_nic_info, dest_nic_name, dest_node):
            skipped_infiniband += 1
            continue

        # Check if IPs are in the same subnet
        if (
            dest_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
            == source_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
        ):
            return dest_nic_name, skipped_infiniband

    return "", skipped_infiniband


def _setup_nic_monitoring(
    source_nic_info: NicInfo,
    dest_nic_info: NicInfo,
    remove_module: bool,
    turn_off_lower: bool,
    source_node: RemoteNode,
) -> tuple[str, str, str, str]:
    """Setup NIC monitoring based on configuration.
    Returns (source_nic, dest_nic, source_pci_nic, dest_pci_nic)."""
    source_synthetic_nic = source_nic_info.name
    dest_synthetic_nic = dest_nic_info.name

    # Determine which NIC to monitor for packet counts
    if source_nic_info.lower and source_nic_info.pci_device_name:
        print(f"source_nic_info: {source_nic_info}")
        source_pci_nic = source_nic_info.pci_device_name
        source_nic = source_pci_nic
    else:
        source_pci_nic = source_nic_info.name
        source_nic = source_synthetic_nic

    if dest_nic_info.lower and dest_nic_info.pci_device_name:
        print(f"dest_nic_info: {dest_nic_info}")
        dest_pci_nic = dest_nic_info.pci_device_name
        dest_nic = dest_pci_nic
    else:
        dest_pci_nic = dest_nic_info.name
        dest_nic = dest_synthetic_nic

    # Override if needed for specific scenarios
    if remove_module or turn_off_lower or isinstance(source_node.os, BSD):
        source_nic = source_synthetic_nic
        dest_nic = dest_synthetic_nic

    print(f"source_nic: {source_nic}, dest_nic: {dest_nic}, source_pci_nic: {source_pci_nic}, dest_pci_nic: {dest_pci_nic}")
    return source_nic, dest_nic, source_pci_nic, dest_pci_nic


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

    # Track statistics for validation
    tested_nic_pairs = 0
    skipped_infiniband_source = 0
    skipped_infiniband_dest = 0

    # for each nic on source node, find the same subnet nic on dest node
    for source_nic_name, source_nic_info in vm_nics[source_node.name].items():
        source_node.log.debug(
            f"Processing NIC {source_nic_name}: {source_nic_info} on {source_node.name}"
        )

        # Use helper function for validation
        if _validate_and_skip_nic(source_nic_info, source_nic_name, source_node):
            skipped_infiniband_source += 1
            continue

        # Find matching destination NIC
        matched_dest_nic_name, skipped = _find_matching_dest_nic(
            source_nic_info, vm_nics, dest_node
        )
        skipped_infiniband_dest += skipped

        if not matched_dest_nic_name:
            source_node.log.warning(
                f"No matching subnet found for {source_nic_info.ip_addr} from "
                f"{source_node.name} on {dest_node.name}. This might indicate "
                f"a network configuration issue."
            )
            continue

        tested_nic_pairs += 1

        # set source and dest network info
        dest_nic_info = vm_nics[dest_node.name][matched_dest_nic_name]
        dest_ip = dest_nic_info.ip_addr
        source_ip = source_nic_info.ip_addr
        source_synthetic_nic = source_nic_info.name

        # Setup NIC monitoring
        source_nic, dest_nic, source_pci_nic, dest_pci_nic = _setup_nic_monitoring(
            source_nic_info, dest_nic_info, remove_module, turn_off_lower, source_node
        )

        source_node.log.debug(
            f"Testing connection from {source_ip} ({source_nic_info.name})"
            f" on {source_node.name} "
            f"to {dest_ip} ({dest_nic_info.name}) on {dest_node.name}"
        )

        # turn off lower device
        if turn_off_lower:
            if source_nic_info.lower:
                source_node.tools[Ip].down(source_pci_nic)
            if dest_nic_info.lower:
                dest_node.tools[Ip].down(dest_pci_nic)

        # Perform file transfer to test connectivity
        _test_file_transferring(
            source_node,
            dest_node,
            source_ip,
            dest_ip,
            source_nic,
            dest_nic,
            source_synthetic_nic,
        )

        # turn on lower device, if turned off before
        if turn_off_lower:
            if source_nic_info.lower:
                source_node.tools[Ip].up(source_pci_nic)
            if dest_nic_info.lower:
                dest_node.tools[Ip].up(dest_pci_nic)

    # After testing all NICs, ensure at least one valid pair was tested
    assert_that(tested_nic_pairs).described_as(
        f"No valid SR-IOV NIC pairs were tested. "
        f"Skipped {skipped_infiniband_source} InfiniBand NICs on source node "
        f"and {skipped_infiniband_dest} on destination node. "
        f"This could indicate all NICs are InfiniBand or there are no "
        f"matching subnets."
    ).is_greater_than(0)

    source_node.log.info(
        f"Successfully tested {tested_nic_pairs} SR-IOV NIC pair(s). "
        f"Skipped {skipped_infiniband_source + skipped_infiniband_dest} "
        f"InfiniBand interface(s)."
    )


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
