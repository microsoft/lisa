# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
import time
from typing import Any, Dict

from lisa import (
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Disk
from lisa.features.network_interface import Synthetic
from lisa.messages import DiskSetupType, DiskType
from lisa.node import RemoteNode
from lisa.tools import Ip, Lscpu, Qemu
from lisa.util.logger import Logger
from microsoft.testsuites.nested.common import (
    connect_nested_vm,
    parse_nested_image_variables,
)
from microsoft.testsuites.performance.common import (
    perf_disk,
    perf_ntttcp,
    reset_partitions,
    reset_raid,
    stop_raid,
)


@TestSuiteMetadata(
    area="storage",
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
    _BR_ADDR = "192.168.1.10"
    _SERVER_IP_ADDR = "192.168.1.14"
    _CLIENT_IP_ADDR = "192.168.1.15"
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
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1),
            ),
        ),
    )
    def perf_nested_kvm_storage_singledisk(
        self, node: RemoteNode, environment: Environment, variables: Dict[str, Any]
    ) -> None:
        self._storage_perf_qemu(node, environment, variables, setup_raid=False)

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM using fio tool with raid0
        configuratrion of 6 l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=6),
            ),
        ),
    )
    def perf_nested_kvm_storage_multidisk(
        self, node: RemoteNode, environment: Environment, variables: Dict[str, Any]
    ) -> None:
        self._storage_perf_qemu(node, environment, variables)

    @TestCaseMetadata(
        description="""
        This test case runs ntttcp test on two nested VMs on same L1 guest
        connected with private bridge
        """,
        priority=3,
        timeout=_TIME_OUT,
    )
    def perf_nested_kvm_ntttcp_private_bridge(
        self,
        node: RemoteNode,
        environment: Environment,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        (
            nested_image_username,
            nested_image_password,
            _,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        try:
            # setup bridge and taps
            node.tools[Ip].setup_bridge(self._BR_NAME, self._BR_ADDR)
            node.tools[Ip].setup_tap(self._CLIENT_TAP, self._BR_NAME)
            node.tools[Ip].setup_tap(self._SERVER_TAP, self._BR_NAME)

            # setup server and client
            server = connect_nested_vm(
                node,
                nested_image_username,
                nested_image_password,
                self._SERVER_HOST_FWD_PORT,
                nested_image_url,
                image_name=self._SERVER_IMAGE,
                nic_model="virtio-net-pci",
                taps=[self._SERVER_TAP],
                name="server",
                log=log,
            )
            server.tools[Ip].add_ipv4_address(self._NIC_NAME, self._SERVER_IP_ADDR)
            server.tools[Ip].up(self._NIC_NAME)
            server.internal_address = self._SERVER_IP_ADDR
            server.nics.default_nic = self._NIC_NAME
            server.capability.network_interface = Synthetic()

            client = connect_nested_vm(
                node,
                nested_image_username,
                nested_image_password,
                self._CLIENT_HOST_FWD_PORT,
                nested_image_url,
                image_name=self._CLIENT_IMAGE,
                nic_model="virtio-net-pci",
                taps=[self._CLIENT_TAP],
                name="client",
                stop_existing_vm=False,
                log=log,
            )
            client.tools[Ip].add_ipv4_address(self._NIC_NAME, self._CLIENT_IP_ADDR)
            client.tools[Ip].up(self._NIC_NAME)
            client.nics.default_nic = self._NIC_NAME
            client.capability.network_interface = Synthetic()

            # run ntttcp test
            perf_ntttcp(
                environment, server, client, test_case_name=inspect.stack()[1][3]
            )
        finally:
            # clear bridge and taps
            node.tools[Ip].delete_interface(self._BR_NAME)
            node.tools[Ip].delete_interface(self._SERVER_TAP)
            node.tools[Ip].delete_interface(self._CLIENT_TAP)

            # stop running QEMU instances
            node.tools[Qemu].stop_vm()

    def _storage_perf_qemu(
        self,
        node: RemoteNode,
        environment: Environment,
        variables: Dict[str, Any],
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

        l1_data_disks = node.features[Disk].get_raw_data_disks()
        l1_data_disk_count = len(l1_data_disks)

        # setup raid on l1 data disks
        if setup_raid:
            disks = ["md0"]
            l1_partition_disks = reset_partitions(node, l1_data_disks)
            stop_raid(node)
            reset_raid(node, l1_partition_disks)
        else:
            disks = ["sdb"]

        # get l2 vm
        l2_vm = connect_nested_vm(
            node,
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
            disks=disks,
        )

        # Qemu command exits immediately but the VM requires some time to boot up.
        time.sleep(60)
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

        # run fio test
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
            environment=environment,
            num_jobs=num_jobs,
            size_gb=8,
            overwrite=True,
        )
