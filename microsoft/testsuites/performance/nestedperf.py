# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
from typing import Any, Dict, cast

from lisa import (
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk, NestedVirtualization
from lisa.features.network_interface import Synthetic
from lisa.messages import DiskSetupType, DiskType
from lisa.node import RemoteNode
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE, READY
from lisa.testsuite import TestResult
from lisa.tools import (
    Dnsmasq,
    HyperV,
    Ip,
    Iptables,
    Lsblk,
    Lscpu,
    Mdadm,
    PowerShell,
    Qemu,
    StartConfiguration,
    Sysctl,
)
from lisa.util import constants
from lisa.util.logger import Logger
from lisa.util.shell import try_connect
from microsoft.testsuites.nested.common import (
    HYPERV_NAT_NAME,
    NESTED_VM_REQUIRED_DISK_SIZE_IN_GB,
    hyperv_connect_nested_vm,
    hyperv_remove_nested_vm,
    parse_nested_image_variables,
    qemu_connect_nested_vm,
)
from microsoft.testsuites.performance.common import (
    perf_disk,
    perf_ntttcp,
    perf_tcp_pps,
    reset_partitions,
    reset_raid,
    stop_raid,
)


@TestSuiteMetadata(
    area="nested",
    category="performance",
    description="""
    This test suite is to validate performance of nested VM using FIO tool.
    """,
)
class KVMPerformance(TestSuite):  # noqa
    _TIME_OUT = 12000
    _CLIENT_IMAGE = "nestedclient.qcow2"
    _SERVER_IMAGE = "nestedserver.qcow2"
    _SERVER_HOST_FWD_PORT = 60022
    _CLIENT_HOST_FWD_PORT = 60023
    _BR_NAME = "br0"
    _BR_NETWORK = "192.168.53.0"
    _BR_CIDR = "24"
    _BR_GATEWAY = "192.168.53.1"
    _SERVER_IP_ADDR = "192.168.53.14"
    _CLIENT_IP_ADDR = "192.168.53.15"
    _SERVER_TAP = "tap0"
    _CLIENT_TAP = "tap1"
    _NIC_NAME = "ens4"

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM using fio tool
        with single l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                os_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=2),
            ),
            supported_features=[NestedVirtualization],
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_nested_kvm_storage_singledisk(
        self,
        node: RemoteNode,
        variables: Dict[str, Any],
        log: Logger,
        result: TestResult,
    ) -> None:
        self._storage_perf_qemu(node, result, variables, log, setup_raid=False)

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM using fio tool with raid0
        configuration of 6 l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                os_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=7),
            ),
            supported_features=[NestedVirtualization],
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_nested_kvm_storage_multidisk(
        self,
        node: RemoteNode,
        result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        self._storage_perf_qemu(node, result, variables, log)

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM in hyper-v
        using fio tool with single l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            supported_os=[Windows],
            supported_platform_type=[AZURE, READY],
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardSSDLRS,
                os_disk_type=schema.DiskType.StandardSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1),
            ),
            supported_features=[NestedVirtualization],
        ),
    )
    def perf_nested_hyperv_storage_singledisk(
        self,
        node: RemoteNode,
        result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        self._storage_perf_hyperv(node, result, variables, log)

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM using fio tool with raid0
        configuration of 6 l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            supported_os=[Windows],
            supported_platform_type=[AZURE, READY],
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardSSDLRS,
                os_disk_type=schema.DiskType.StandardSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=6),
            ),
            supported_features=[NestedVirtualization],
        ),
    )
    def perf_nested_hyperv_storage_multidisk(
        self,
        node: RemoteNode,
        result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        self._storage_perf_hyperv(node, result, variables, log, setup_raid=True)

    @TestCaseMetadata(
        description="""
        This test case runs ntttcp test on two nested VMs on same L1 guest
        connected with private bridge
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            min_core_count=16,
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=12),
            ),
            supported_features=[NestedVirtualization],
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_nested_kvm_ntttcp_private_bridge(
        self,
        node: RemoteNode,
        result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        (
            nested_image_username,
            nested_image_password,
            _,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        # get cpu count
        cpu_count = node.tools[Lscpu].get_core_count()

        try:
            # setup bridge
            node.tools[Ip].setup_bridge(
                self._BR_NAME, f"{self._BR_GATEWAY}/{self._BR_CIDR}"
            )

            # setup server and client
            server = qemu_connect_nested_vm(
                node,
                nested_image_username,
                nested_image_password,
                self._SERVER_HOST_FWD_PORT,
                nested_image_url,
                image_name=self._SERVER_IMAGE,
                nic_model="virtio-net-pci",
                taps=1,
                cores=cpu_count,
                bridge=self._BR_NAME,
                name="server",
                log=log,
            )
            server.tools[Ip].add_ipv4_address(
                self._NIC_NAME, f"{self._SERVER_IP_ADDR}/{self._BR_CIDR}", persist=True
            )
            server.tools[Ip].up(self._NIC_NAME, persist=True)
            server.internal_address = self._SERVER_IP_ADDR
            server.capability.network_interface = Synthetic()

            client = qemu_connect_nested_vm(
                node,
                nested_image_username,
                nested_image_password,
                self._CLIENT_HOST_FWD_PORT,
                nested_image_url,
                image_name=self._CLIENT_IMAGE,
                nic_model="virtio-net-pci",
                taps=1,
                cores=cpu_count,
                bridge=self._BR_NAME,
                name="client",
                stop_existing_vm=False,
                log=log,
            )
            client.tools[Ip].add_ipv4_address(
                self._NIC_NAME, f"{self._CLIENT_IP_ADDR}/{self._BR_CIDR}", persist=True
            )
            client.tools[Ip].up(self._NIC_NAME, persist=True)
            client.capability.network_interface = Synthetic()

            # run ntttcp test
            perf_ntttcp(
                result,
                server,
                client,
                server_nic_name=self._NIC_NAME,
                client_nic_name=self._NIC_NAME,
                test_case_name=inspect.stack()[1][3],
            )
        finally:
            try:
                # stop running QEMU instances
                node.tools[Qemu].delete_vm()

                # clear bridge and taps
                node.tools[Ip].delete_interface(self._BR_NAME)
            except Exception as e:
                log.debug(f"Failed to clean up vm: {e}")
                node.mark_dirty()

    @TestCaseMetadata(
        description="""
        This script runs ntttcp test on two nested VMs on different L1 guests
        connected with NAT
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=16,
            network_interface=schema.NetworkInterfaceOptionSettings(
                nic_count=search_space.IntRange(min=2),
            ),
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=12),
            ),
            supported_features=[NestedVirtualization],
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_nested_kvm_ntttcp_different_l1_nat(
        self,
        result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        server_l1 = cast(RemoteNode, environment.nodes[0])
        client_l1 = cast(RemoteNode, environment.nodes[1])

        # parse nested image variables
        (
            nested_image_username,
            nested_image_password,
            _,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        try:
            # setup nested vm on server in NAT configuration
            server_l2 = self._linux_setup_nat(
                node=server_l1,
                nested_vm_name="server_l2",
                guest_username=nested_image_username,
                guest_password=nested_image_password,
                guest_port=self._SERVER_HOST_FWD_PORT,
                guest_image_url=nested_image_url,
                guest_internal_ip=self._SERVER_IP_ADDR,
                guest_default_nic=self._NIC_NAME,
                bridge_name=self._BR_NAME,
                bridge_network=self._BR_NETWORK,
                bridge_cidr=self._BR_CIDR,
                bridge_gateway=self._BR_GATEWAY,
            )

            # setup nested vm on client in NAT configuration
            client_l2 = self._linux_setup_nat(
                node=client_l1,
                nested_vm_name="client_l2",
                guest_username=nested_image_username,
                guest_password=nested_image_password,
                guest_port=self._CLIENT_HOST_FWD_PORT,
                guest_image_url=nested_image_url,
                guest_internal_ip=self._CLIENT_IP_ADDR,
                guest_default_nic=self._NIC_NAME,
                bridge_name=self._BR_NAME,
                bridge_network=self._BR_NETWORK,
                bridge_cidr=self._BR_CIDR,
                bridge_gateway=self._BR_GATEWAY,
            )

            # run ntttcp test
            perf_ntttcp(
                result,
                server_l2,
                client_l2,
                server_nic_name=self._NIC_NAME,
                client_nic_name=self._NIC_NAME,
                lagscope_server_ip=self._SERVER_IP_ADDR,
                test_case_name=inspect.stack()[1][3],
            )
        finally:
            self._linux_cleanup_nat(server_l1, self._BR_NAME, log)
            self._linux_cleanup_nat(client_l1, self._BR_NAME, log)

    @TestCaseMetadata(
        description="""
        This script runs ntttcp test on two nested VMs on different L1 guests
        connected with NAT
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            supported_os=[Windows],
            supported_platform_type=[AZURE, READY],
            supported_features=[NestedVirtualization],
        ),
    )
    def perf_nested_hyperv_ntttcp_different_l1_nat(
        self,
        result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        server_l1 = cast(RemoteNode, environment.nodes[0])
        client_l1 = cast(RemoteNode, environment.nodes[1])

        # parse nested image variables
        (
            nested_image_username,
            nested_image_password,
            _,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        try:
            # setup nested vm on server in NAT configuration
            server_l2 = self._windows_setup_nat(
                node=server_l1,
                nested_vm_name="server_l2",
                guest_username=nested_image_username,
                guest_password=nested_image_password,
                guest_port=self._SERVER_HOST_FWD_PORT,
                guest_image_url=nested_image_url,
            )

            # setup nested vm on client in NAT configuration
            client_l2 = self._windows_setup_nat(
                node=client_l1,
                nested_vm_name="client_l2",
                guest_username=nested_image_username,
                guest_password=nested_image_password,
                guest_port=self._CLIENT_HOST_FWD_PORT,
                guest_image_url=nested_image_url,
            )

            # run ntttcp test
            perf_ntttcp(
                result,
                server_l2,
                client_l2,
                test_case_name=inspect.stack()[1][3],
            )
        finally:
            # cleanup server
            try:
                hyperv_remove_nested_vm(server_l1, "server_l2")
            except Exception as e:
                log.debug(f"Failed to clean up server vm: {e}")
                server_l1.mark_dirty()

            # cleanup client
            try:
                hyperv_remove_nested_vm(client_l1, "client_l2")
            except Exception as e:
                log.debug(f"Failed to clean up client vm: {e}")
                client_l1.mark_dirty()

    @TestCaseMetadata(
        description="""
        This script runs netperf test on two nested VMs on different L1 guests
        connected with NAT
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                nic_count=search_space.IntRange(min=2),
            ),
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=12),
            ),
            supported_features=[NestedVirtualization],
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_nested_kvm_netperf_pps_nat(
        self,
        result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        server_l1 = cast(RemoteNode, environment.nodes[0])
        client_l1 = cast(RemoteNode, environment.nodes[1])

        # parse nested image variables
        (
            nested_image_username,
            nested_image_password,
            _,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        try:
            # setup nested vm on server in NAT configuration
            server_l2 = self._linux_setup_nat(
                node=server_l1,
                nested_vm_name="server_l2",
                guest_username=nested_image_username,
                guest_password=nested_image_password,
                guest_port=self._SERVER_HOST_FWD_PORT,
                guest_image_url=nested_image_url,
                guest_internal_ip=self._SERVER_IP_ADDR,
                guest_default_nic=self._NIC_NAME,
                bridge_name=self._BR_NAME,
                bridge_network=self._BR_NETWORK,
                bridge_cidr=self._BR_CIDR,
                bridge_gateway=self._BR_GATEWAY,
            )

            # setup nested vm on client in NAT configuration
            client_l2 = self._linux_setup_nat(
                node=client_l1,
                nested_vm_name="client_l2",
                guest_username=nested_image_username,
                guest_password=nested_image_password,
                guest_port=self._CLIENT_HOST_FWD_PORT,
                guest_image_url=nested_image_url,
                guest_internal_ip=self._CLIENT_IP_ADDR,
                guest_default_nic=self._NIC_NAME,
                bridge_name=self._BR_NAME,
                bridge_network=self._BR_NETWORK,
                bridge_cidr=self._BR_CIDR,
                bridge_gateway=self._BR_GATEWAY,
            )

            # run netperf test
            perf_tcp_pps(result, "singlepps", server_l2, client_l2)
        finally:
            self._linux_cleanup_nat(server_l1, self._BR_NAME, log)
            self._linux_cleanup_nat(client_l1, self._BR_NAME, log)

    def _linux_setup_nat(
        self,
        node: RemoteNode,
        nested_vm_name: str,
        guest_username: str,
        guest_password: str,
        guest_port: int,
        guest_image_url: str,
        guest_internal_ip: str,
        guest_default_nic: str,
        bridge_name: str,
        bridge_network: str,
        bridge_cidr: str,
        bridge_gateway: str,
    ) -> RemoteNode:
        """
        Setup NAT on the node with following configurations:
        1. Forward traffic on node's eth0 interface and port `guest_port`
        to the nested VM's port 22.
        2. Forward all traffic on node's eth1 interface to the nested VM.
        """
        # get core count
        core_count = node.tools[Lscpu].get_core_count()

        node_eth1_ip = node.nics.get_nic("eth1").ip_addr
        bridge_dhcp_range = f"{guest_internal_ip},{guest_internal_ip}"

        # enable ip forwarding
        node.tools[Sysctl].write("net.ipv4.ip_forward", "1")

        # setup bridge
        node.tools[Ip].setup_bridge(bridge_name, f"{bridge_gateway}/{bridge_cidr}")
        node.tools[Ip].set_bridge_configuration(bridge_name, "stp_state", "0")
        node.tools[Ip].set_bridge_configuration(bridge_name, "forward_delay", "0")

        # reset bridge lease file to remove old dns leases
        node.execute(
            f"cp /dev/null /var/run/qemu-dnsmasq-{bridge_name}.leases", sudo=True
        )

        # start dnsmasq
        node.tools[Dnsmasq].start(bridge_name, bridge_gateway, bridge_dhcp_range)

        # reset filter table to accept all traffic
        node.tools[Iptables].reset_table()

        # reset nat table and setup nat forwarding
        node.tools[Iptables].reset_table("nat")
        node.tools[Iptables].run(
            f"-t nat -A POSTROUTING -s {bridge_network}/{bridge_cidr} -j MASQUERADE",
            sudo=True,
            force_run=True,
        )

        # start nested vm
        nested_vm = qemu_connect_nested_vm(
            node,
            guest_username,
            guest_password,
            guest_port,
            guest_image_url,
            taps=1,
            cores=core_count,
            bridge=bridge_name,
            stop_existing_vm=True,
            name=nested_vm_name,
        )

        # configure rc.local to run dhclient on reboot
        nested_vm.tools[StartConfiguration].add_command("ip link set dev ens4 up")
        nested_vm.tools[StartConfiguration].add_command("dhclient ens4")

        # reboot nested vm and close ssh connection
        nested_vm.execute("reboot", sudo=True)
        nested_vm.close()

        # route traffic on `eth0` and port `guest_port` on l1 vm to
        # port 22 on l2 vm
        node.tools[Iptables].run(
            f"-t nat -A PREROUTING -i eth0 -p tcp --dport {guest_port} "
            f"-j DNAT --to {guest_internal_ip}:22",
            sudo=True,
            force_run=True,
        )

        # route all tcp traffic on `eth1` port on l1 vm to l2 vm
        node.tools[Iptables].run(
            f"-t nat -A PREROUTING -i eth1 -d {node_eth1_ip} "
            f"-p tcp -j DNAT --to {guest_internal_ip}",
            sudo=True,
            force_run=True,
        )

        # wait till nested vm is up
        try_connect(
            schema.ConnectionInfo(
                address=node.connection_info[
                    constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
                ],
                port=guest_port,
                username=guest_username,
                password=guest_password,
            )
        )

        # set default nic interfaces on l2 vm
        nested_vm.internal_address = node_eth1_ip
        nested_vm.capability.network_interface = Synthetic()

        return nested_vm

    def _linux_cleanup_nat(
        self,
        node: RemoteNode,
        bridge_name: str,
        log: Logger,
    ) -> None:
        try:
            # stop running QEMU instances
            node.tools[Qemu].delete_vm()

            # clear bridge and taps
            node.tools[Ip].delete_interface(bridge_name)

            # flush ip tables
            node.tools[Iptables].reset_table()
            node.tools[Iptables].reset_table("nat")
        except Exception as e:
            log.debug(f"Failed to clean up NAT configuration: {e}")
            node.mark_dirty()

    def _storage_perf_qemu(
        self,
        node: RemoteNode,
        result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
        filename: str = "/dev/sdb",
        start_iodepth: int = 1,
        max_iodepth: int = 1024,
        setup_raid: bool = True,
    ) -> None:
        (
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        # get data disks and remove disk we will use for downloading
        # nested image
        l1_data_disks = node.features[Disk].get_raw_data_disks()
        log.debug(f"l1_data_disks: {l1_data_disks}")

        image_download_location = node.find_partition_with_freespace(
            NESTED_VM_REQUIRED_DISK_SIZE_IN_GB
        )
        image_download_disk = (
            node.tools[Lsblk]
            .find_disk_by_mountpoint(image_download_location, force_run=True)
            .device_name
        )
        log.debug(f"image_download_disk: {image_download_disk}")

        if image_download_disk in l1_data_disks:
            l1_data_disks.remove(image_download_disk)

        l1_data_disk_count = len(l1_data_disks)

        try:
            # setup raid on l1 data disks
            if setup_raid:
                disks = ["/dev/md0"]
                l1_partition_disks = reset_partitions(node, l1_data_disks)
                stop_raid(node)
                reset_raid(node, l1_partition_disks)
            else:
                disks = [l1_data_disks[0]]

            # get l2 vm
            l2_vm = qemu_connect_nested_vm(
                node,
                nested_image_username,
                nested_image_password,
                nested_image_port,
                nested_image_url,
                disks=disks,
            )
            l2_vm.capability.network_interface = Synthetic()

            # Qemu command exits immediately but the VM requires some time to boot up.
            l2_vm.tools[Lscpu].get_core_count()

            # Each fio process start jobs equal to the iodepth to read/write from
            # the disks. The max number of jobs can be equal to the core count of
            # the node.
            # Examples:
            # iodepth = 4, core count = 8 => max_jobs = 4
            # iodepth = 16, core count = 8 => max_jobs = 8
            num_jobs = []
            iodepth_iter = start_iodepth
            core_count = node.tools[Lscpu].get_core_count()
            while iodepth_iter <= max_iodepth:
                num_jobs.append(min(iodepth_iter, core_count))
                iodepth_iter = iodepth_iter * 2

            # Run fio test
            # The added disks appear as /dev/sdb on the nested vm
            perf_disk(
                l2_vm,
                start_iodepth,
                max_iodepth,
                filename,
                test_name=inspect.stack()[1][3],
                core_count=core_count,
                disk_count=l1_data_disk_count,
                disk_setup_type=DiskSetupType.raid0,
                disk_type=DiskType.premiumssd,
                test_result=result,
                num_jobs=num_jobs,
                size_mb=8192,
                overwrite=True,
            )
        finally:
            try:
                node.tools[Qemu].delete_vm()
                stop_raid(node)
            except Exception as e:
                log.debug(f"Failed to cleanup Qemu VM: {e}")
                node.mark_dirty()

    def _storage_perf_hyperv(
        self,
        node: RemoteNode,
        test_result: TestResult,
        variables: Dict[str, Any],
        log: Logger,
        filename: str = "/dev/sdb",
        start_iodepth: int = 1,
        max_iodepth: int = 1024,
        setup_raid: bool = False,
    ) -> None:
        (
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        mdadm = node.tools[Mdadm]

        try:
            # cleanup any previous raid configurations to free
            # data disks
            mdadm.stop_raid()

            # get data disk id
            powershell = node.tools[PowerShell]
            data_disks_id_str = powershell.run_cmdlet(
                "(Get-Disk | "
                "Where-Object {$_.FriendlyName -eq 'Msft Virtual Disk'}).Number"
            )
            data_disks_id = data_disks_id_str.strip().replace("\r", "").split("\n")

            # set data disks offline
            for disk in data_disks_id:
                powershell.run_cmdlet(
                    f"Set-Disk -Number {disk} -IsOffline $true", force_run=True
                )

            # create raid
            if setup_raid:
                mdadm.create_raid(data_disks_id)

            # get l2 vm
            nested_vm = hyperv_connect_nested_vm(
                node,
                nested_image_username,
                nested_image_password,
                nested_image_port,
                nested_image_url,
            )

            # Each fio process start jobs equal to the iodepth to read/write from
            # the disks. The max number of jobs can be equal to the core count of
            # the node.
            # Examples:
            # iodepth = 4, core count = 8 => max_jobs = 4
            # iodepth = 16, core count = 8 => max_jobs = 8
            num_jobs = []
            iodepth_iter = start_iodepth
            core_count = node.tools[Lscpu].get_core_count()
            while iodepth_iter <= max_iodepth:
                num_jobs.append(min(iodepth_iter, core_count))
                iodepth_iter = iodepth_iter * 2

            # run fio test
            perf_disk(
                nested_vm,
                start_iodepth,
                max_iodepth,
                filename,
                test_name=inspect.stack()[1][3],
                core_count=core_count,
                disk_count=1,
                disk_setup_type=DiskSetupType.raid0,
                disk_type=DiskType.premiumssd,
                test_result=test_result,
                num_jobs=num_jobs,
                size_mb=8192,
                overwrite=True,
            )
        finally:
            try:
                hyperv_remove_nested_vm(node)
                node.tools[Mdadm].stop_raid()
            except Exception as e:
                log.debug(f"Failed to cleanup Hyper-V vm: {e}")
                node.mark_dirty()

    def _windows_setup_nat(
        self,
        node: RemoteNode,
        nested_vm_name: str,
        guest_username: str,
        guest_password: str,
        guest_port: int,
        guest_image_url: str,
    ) -> RemoteNode:
        nested_vm = hyperv_connect_nested_vm(
            node,
            guest_username,
            guest_password,
            guest_port,
            guest_image_url,
            name=nested_vm_name,
        )

        # ntttcp uses port in the range (5000, 5065)
        # map all traffic on these ports to the guest vm
        local_ip = node.tools[HyperV].get_ip_address(nested_vm_name)
        for i in range(5000, 5065):
            node.tools[HyperV].setup_port_forwarding(
                nat_name=HYPERV_NAT_NAME, host_port=i, guest_port=i, guest_ip=local_ip
            )

        return nested_vm
