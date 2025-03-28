# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
import time
from assertpy import assert_that
from lisa.features import Disk
from lisa.tools import Lsblk
from lisa.schema import DiskType
from typing import List
from lisa import (
    BadEnvironmentStateException,
    Logger,
    PassedException,
    RemoteNode,
    SkippedException,
    TcpConnectionException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    create_timer,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import EnvironmentStatus
from lisa.features import (
    AvailabilityZoneEnabled,
    DiskEphemeral,
    DiskPremiumSSDLRS,
    DiskStandardSSDLRS,
    NetworkInterface,
    SerialConsole,
    Sriov,
    StartStop,
    Synthetic,
)
from lisa.tools import Lspci
from lisa.util import constants
from lisa.util.shell import wait_tcp_port_ready


@TestSuiteMetadata(
    area="provisioning",
    category="functional",
    description="""
    This test suite uses to verify if an environment can be provisioned correct or not.

    - The basic smoke test can run on all images to determinate if a image can boot and
    reboot.
    - Other provisioning tests verify if an environment can be provisioned with special
    hardware configurations.
    """,
)
class Provisioning(TestSuite):
    TIME_OUT = 300
    PLATFORM_TIME_OUT = 600

    @TestCaseMetadata(
        description="""
        This case verifies whether a node is operating normally.

        Steps,
        1. Connect to TCP port 22. If it's not connectable, failed and check whether
            there is kernel panic.
        2. Connect to SSH port 22, and reboot the node. If there is an error and kernel
            panic, fail the case. If it's not connectable, also fail the case.
        3. If there is another error, but not kernel panic or tcp connection, pass with
            warning.
        4. Otherwise, fully passed.
        """,
        priority=0,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole],
        ),
    )
    def smoke_test(self, log: Logger, node: RemoteNode, log_path: Path) -> None:
        self._smoke_test(log, node, log_path, "smoke_test")

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with synthetic nic.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            network_interface=Synthetic(),
            supported_features=[SerialConsole],
        ),
    )
    def verify_deployment_provision_synthetic_nic(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log, node, log_path, "verify_deployment_provision_synthetic_nic"
        )

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with standard ssd disk.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            disk=DiskStandardSSDLRS(),
            supported_features=[SerialConsole],
        ),
    )
    def verify_deployment_provision_standard_ssd_disk(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log, node, log_path, "verify_deployment_provision_standard_ssd_disk"
        )

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with ephemeral disk.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            disk=DiskEphemeral(),
            supported_features=[SerialConsole],
        ),
    )
    def verify_deployment_provision_ephemeral_managed_disk(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log, node, log_path, "verify_deployment_provision_ephemeral_managed_disk"
        )

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with premium disk.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            disk=DiskPremiumSSDLRS(),
            supported_features=[SerialConsole],
        ),
    )
    def verify_deployment_provision_premium_disk(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log, node, log_path, "verify_deployment_provision_premium_disk"
        )

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with premium disk.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumV2SSDLRS,
                data_disk_count=search_space.IntRange(min=1),
            ),
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole, AvailabilityZoneEnabled()],
        ),
    )
    def verify_deployment_provision_premiumv2_disk(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log, node, log_path, "verify_deployment_provision_premiumv2_disk"
        )
        i=0
        while i<1000:
            i+=1
            time.sleep(1)
            disk = node.features[Disk]
            disks_added = self.hot_add_disk_parallel(log, node, DiskType.PremiumV2SSDLRS, 20)
            log.info(f"disk added {i}th time: {disks_added}")
            assert_that(disks_added).is_length(8)
            all_disks = disk.get_all_disks()
            log.info(f"all disks post adding {i}th time: {all_disks}")
            assert_that(all_disks).is_length(10)

            self.remove_data_disk(log, node, disks_added)
            all_disks = disk.get_all_disks()
            log.info(f"all disks after removing {i}th time: {all_disks}")
            assert_that(all_disks).is_length(2)

        # disks_added = self.hot_add_disk_parallel(log, node, DiskType.PremiumV2SSDLRS, 20)
        # log.info(f"disk added second time: {disks_added}")
        # all_disks = disk.get_all_disks()
        # log.info(f"all disks post adding second time: {all_disks}")


    def remove_data_disk(self, log, node, disks_added):
        disk = node.features[Disk]
        lsblk = node.tools[Lsblk]
        # remove data disks
        log.debug(f"Removing managed disks: {disks_added}")
        disk.remove_data_disk(disks_added)


        # partition_after_removing_disk = lsblk.get_disks(force_run=True)
        # added_partitions = [
        #     item
        #     for item in partitions_before_adding_disks
        #     if item not in partition_after_removing_disk
        # ]
        # assert_that(added_partitions, "data disks should not be present").is_length(0)


    def hot_add_disk_parallel(
        self, log: Logger, node: RemoteNode, disk_type: DiskType, size: int
    ) -> List[str]:
        disk = node.features[Disk]
        lsblk = node.tools[Lsblk]

        # get max data disk count for the node
        # assert node.capability.disk
        # assert isinstance(
        #     node.capability.disk.max_data_disk_count, int
        # ), f"actual type: {node.capability.disk.max_data_disk_count}"
        # max_data_disk_count = node.capability.disk.max_data_disk_count
        # log.debug(f"max_data_disk_count: {max_data_disk_count}")

        # get the number of data disks already added to the vm
        # assert isinstance(node.capability.disk.data_disk_count, int)
        # current_data_disk_count = node.capability.disk.data_disk_count
        # log.debug(f"current_data_disk_count: {current_data_disk_count}")

        # # disks to be added to the vm
        # disks_to_add = max_data_disk_count - current_data_disk_count

        # if disks_to_add < 1:
        #     raise SkippedException(
        #         "No data disks can be added. "
        #         "Consider manually setting max_data_disk_count in the runbook."
        #     )

        # get partition info before adding data disks
        partitions_before_adding_disks = lsblk.get_disks(force_run=True)

        # # add data disks
        # log.debug(f"Adding {disks_to_add} managed disks")
        disks_added = disk.add_data_disk(8, disk_type, size)

        # verify that partition count is increased by disks_to_add
        # and the size of partition is correct
        timeout = 30
        timer = create_timer()
        while timeout > timer.elapsed(False):
            partitons_after_adding_disks = lsblk.get_disks(force_run=True)
            added_partitions = [
                item
                for item in partitons_after_adding_disks
                if item not in partitions_before_adding_disks
            ]
            if len(added_partitions) == 8:
                break
            else:
                log.debug(f"added disks count: {len(added_partitions)}")
                time.sleep(1)
        assert_that(
            added_partitions, f"8 disks should be added"
        ).is_length(8)
        for partition in added_partitions:
            assert_that(
                partition.size_in_gb,
                f"data disk {partition.name} size should be equal to {size} GB",
            ).is_equal_to(size)

        # # remove data disks
        # log.debug(f"Removing managed disks: {disks_added}")
        # disk.remove_data_disk(disks_added)

        # verify that partition count is decreased by disks_to_add


        # partition_after_removing_disk = lsblk.get_disks(force_run=True)
        # added_partitions = [
        #     item
        #     for item in partitions_before_adding_disks
        #     if item not in partition_after_removing_disk
        # ]
        # assert_that(added_partitions, "data disks should not be present").is_length(0)

        return disks_added




    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with sriov.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            network_interface=Sriov(),
            supported_features=[SerialConsole],
        ),
    )
    def verify_deployment_provision_sriov(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self.check_sriov(log, node)
        self._smoke_test(log, node, log_path, "verify_deployment_provision_sriov")
        self.check_sriov(log, node)

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned.
        The test steps are almost the same as `smoke_test` except for
        executing reboot from Azure SDK.
        """,
        priority=2,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole, StartStop],
        ),
    )
    def verify_reboot_in_platform(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log,
            node,
            log_path,
            reboot_in_platform=True,
            case_name="verify_reboot_in_platform",
        )

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with an ultra datadisk.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.UltraSSDLRS,
                data_disk_count=search_space.IntRange(min=1),
            ),
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole],
        ),
    )
    def verify_deployment_provision_ultra_datadisk(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log,
            node,
            log_path,
            "verify_deployment_provision_ultra_datadisk",
        )

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned.
        The test steps are almost the same as `smoke_test` except for
        executing stop then start from Azure SDK.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole, StartStop],
        ),
    )
    def verify_stop_start_in_platform(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log,
            node,
            log_path,
            "verify_stop_start_in_platform",
            reboot_in_platform=True,
            is_restart=False,
        )

    def _smoke_test(
        self,
        log: Logger,
        node: RemoteNode,
        log_path: Path,
        case_name: str,
        reboot_in_platform: bool = False,
        wait: bool = True,
        is_restart: bool = True,
    ) -> None:
        if not node.is_remote:
            raise SkippedException(f"smoke test: {case_name} cannot run on local node.")

        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
            node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
            log=log,
            timeout=self.TIME_OUT,
        )
        if not is_ready:
            serial_console = node.features[SerialConsole]
            serial_console.check_panic(
                saved_path=log_path, stage="bootup", force_run=True
            )
            raise TcpConnectionException(
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                tcp_error_code,
                "no panic found in serial log during bootup",
            )
        try:
            timer = create_timer()
            log.info(f"SSH port 22 is opened, connecting and rebooting '{node.name}'")
            # In this step, the underlying shell will connect to SSH port.
            # If successful, the node will be reboot.
            # If failed, It distinguishes TCP and SSH errors by error messages.
            if reboot_in_platform:
                start_stop = node.features[StartStop]
                if is_restart:
                    start_stop.restart(wait=wait)
                else:
                    start_stop.stop(wait=wait)
                    start_stop.start(wait=wait)
                is_ready, tcp_error_code = wait_tcp_port_ready(
                    node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                    node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                    log=log,
                    timeout=self.PLATFORM_TIME_OUT,
                )
                if not is_ready:
                    serial_console = node.features[SerialConsole]
                    serial_console.check_panic(
                        saved_path=log_path, stage="reboot", force_run=True
                    )
                    raise TcpConnectionException(
                        node.connection_info[
                            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
                        ],
                        node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                        tcp_error_code,
                        "no panic found in serial log during reboot",
                    )
            else:
                node.reboot()
            log.info(f"node '{node.name}' rebooted in {timer}")
        except Exception as identifier:
            serial_console = node.features[SerialConsole]
            # if there is any panic, fail before partial pass
            serial_console.check_panic(
                saved_path=log_path, stage="reboot", force_run=True
            )

            # if node cannot be connected after reboot, it should be failed.
            if isinstance(identifier, TcpConnectionException):
                raise BadEnvironmentStateException(f"after reboot, {identifier}")
            raise PassedException(identifier)

    def is_mana_device_discovered(self, node: RemoteNode) -> bool:
        lspci = node.tools[Lspci]
        pci_devices = lspci.get_devices_by_type(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        assert_that(
            len(pci_devices),
            "One or more SRIOV devices are expected to be discovered.",
        ).is_greater_than(0)

        all_mana_devices = False
        for pci_device in pci_devices:
            if (
                "Device 00ba" in pci_device.device_info
                and pci_device.vendor == "Microsoft Corporation"
            ):
                all_mana_devices = True
            else:
                all_mana_devices = False
                break
        return all_mana_devices

    def check_sriov(self, log: Logger, node: RemoteNode) -> None:
        node_nic_info = node.nics
        node_nic_info.initialize()

        network_interface_feature = node.features[NetworkInterface]
        sriov_count = network_interface_feature.get_nic_count()
        log.info(f"check_sriov: sriov_count {sriov_count}")
        pci_nic_check = True
        if self.is_mana_device_discovered(node):
            if not node.nics.is_mana_driver_enabled():
                pci_nic_check = False
            else:
                pci_nic_check = True
        if pci_nic_check:
            log.info(
                f"check_sriov: PCI nic count {len(node_nic_info.get_lower_nics())}"
            )
            assert_that(len(node_nic_info.get_lower_nics())).described_as(
                f"VF count inside VM is {len(node_nic_info.get_lower_nics())},"
                f"actual sriov nic count is {sriov_count}"
            ).is_equal_to(sriov_count)
