# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from statistics import mean, median

from assertpy import assert_that

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
    Disk,
    DiskEphemeral,
    DiskPremiumSSDLRS,
    DiskStandardSSDLRS,
    NetworkInterface,
    SerialConsole,
    Sriov,
    StartStop,
    Synthetic,
)
from lisa.features.security_profile import CvmDisabled
from lisa.tools import Cat, GrubConfig, KernelConfig, Lspci
from lisa.util import LisaException, constants
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
            supported_features=[CvmDisabled()],  # TODO: Fix disk deployment for CVM
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
        This case runs smoke test on a node provisioned with 64 P60 premium disks.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_size=search_space.IntRange(min=8192),  # P60 = 8TB
                data_disk_count=search_space.IntRange(min=64),   # 64 disks
                os_disk_type=schema.DiskType.PremiumSSDLRS,
            ),
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
            supported_features=[AvailabilityZoneEnabled()],
        ),
    )
    def verify_deployment_provision_premiumv2_disk(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        self._smoke_test(
            log, node, log_path, "verify_deployment_provision_premiumv2_disk"
        )

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with sriov.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            network_interface=Sriov(),
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
            supported_features=[StartStop],
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
            supported_features=[StartStop],
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

    @TestCaseMetadata(
        description="""
        This case performs a reboot stress test on the node
        and iterates smoke test 100 times.
        The test steps are almost the same as `smoke_test`.
        The reboot times is summarized after the test is run
        """,
        priority=3,
        timeout=10800,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
        ),
    )
    def stress_reboot(self, log: Logger, node: RemoteNode, log_path: Path) -> None:
        reboot_times = []
        try:
            for i in range(100):
                elapsed = self._smoke_test(log, node, log_path, "stress_reboot")
                reboot_times.append((i + 1, elapsed))
                log.debug(f"Reboot iterations {i + 1}/100 completed in {elapsed:.2f}s")
        except PassedException as e:
            raise LisaException(e)
        finally:
            times = [time for _, time in reboot_times if isinstance(time, (int, float))]
            log.info(f"completed {i + 1}/100 iterations;summary:")
            log.info(f"Min reboot time: {min(times):.2f}s")
            log.info(f"Max reboot time: {max(times):.2f}s")
            log.info(f"Average reboot time: {mean(times):.2f}s")
            log.info(f"Median reboot time: {median(times):.2f}s")

    @TestCaseMetadata(
        description="""
        This test case verifies that the system can boot and provision successfully
        with the swiotlb=force kernel parameter enabled. This kernel parameter
        forces the use of software I/O TLB for all DMA operations.

        This is particularly relevant in Confidential Computing VMs,
        where memory is encrypted and direct DMA access isn't possible.
        In such cases, bounce buffering becomes mandatory.

        Regression: https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=730ff06d3f5cc2ce0348414b78c10528b767d4a3 # noqa

        Steps:
        1. Set the swiotlb=force kernel parameter in grub configuration
        2. Reboot the system to apply the kernel parameter
        3. Run smoke test to verify system functionality
        4. Verify the system is responsive after reboot
        
        TODO: This test is currently unsupported on CVM because modifying boot
        parameters in CVM requires rebuilding, which needs access to kernel image,
        modules, and initramfs all unbundled. With just UEFI image, more research
        is needed to determine if it's possible

        TODO: Ideally this should run on all UEFI scenarios, not just Grub-based
        systems. However, since LISA does not have a common UEFI interface yet,
        we skip non-grub scenarios for now.
        """,
        priority=2,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_deployment_provision_swiotlb_force(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        # Check if CONFIG_SWIOTLB is available in kernel configuration
        kernel_config = node.tools[KernelConfig]
        if not kernel_config.is_enabled("CONFIG_SWIOTLB"):
            raise SkippedException("CONFIG_SWIOTLB is not enabled in kernel")

        try:
            cat = node.tools[Cat]
            try:
                grub_config = node.tools[GrubConfig]
            except Exception as e:
                # Skip if grub is not available on this distribution
                # TODO: Should support UEFI-based parameter modification when
                # LISA has a common UEFI interface
                raise SkippedException(
                    f"GrubConfig is not available on this distribution: {e}"
                )

            # Check disk controller type and set appropriate swiotlb parameters
            disk_feature = node.features[Disk]
            disk_controller_type = disk_feature.get_os_disk_controller_type()
            swiotlb_value = "force"

            if disk_controller_type == schema.DiskControllerType.NVME:
                # For NVMe, use larger pool size: swiotlb=force,524288
                # NVMe devices can have higher I/O throughput and queue depths,
                # requiring more bounce buffer slots to handle concurrent DMA
                # operations. Additionally, NVMe initialization happens early in
                # the boot sequence, and insufficient swiotlb buffers can cause
                # boot failures.
                swiotlb_value = "force,524288"

            log.debug(
                f"Disk controller type: {disk_controller_type}, "
                f"Setting swiotlb kernel parameter to: {swiotlb_value}"
            )
            grub_config.set_kernel_cmdline_arg("swiotlb", swiotlb_value)
            node.reboot()
            cmdline_result = cat.read("/proc/cmdline", sudo=True, force_run=True)
            assert_that(cmdline_result).described_as(
                f"swiotlb={swiotlb_value} kernel parameter should be present in: "
                f"{cmdline_result}"
            ).contains(f"swiotlb={swiotlb_value}")

            self._smoke_test(
                log=log,
                node=node,
                log_path=log_path,
                case_name="verify_deployment_provision_swiotlb_force",
                wait=True,
                is_restart=True,
            )
        finally:
            # Mark node as dirty since we modified kernel parameters
            # This ensures the node won't be reused regardless of test outcome
            node.mark_dirty()

    def _smoke_test(
        self,
        log: Logger,
        node: RemoteNode,
        log_path: Path,
        case_name: str,
        reboot_in_platform: bool = False,
        wait: bool = True,
        is_restart: bool = True,
    ) -> float:
        if not node.is_remote:
            raise SkippedException(f"smoke test: {case_name} cannot run on local node.")

        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
            node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
            log=log,
            timeout=self.TIME_OUT,
        )
        if not is_ready:
            if node.features.is_supported(SerialConsole):
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
                    if node.features.is_supported(SerialConsole):
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
        except Exception as e:
            if node.features.is_supported(SerialConsole):
                serial_console = node.features[SerialConsole]
                # if there is any panic, fail before partial pass
                serial_console.check_panic(
                    saved_path=log_path, stage="reboot", force_run=True
                )

            # if node cannot be connected after reboot, it should be failed.
            if isinstance(e, TcpConnectionException):
                raise BadEnvironmentStateException(f"after reboot, {e}")
            raise PassedException(e)
        return timer.elapsed()

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
            log.info(f"check_sriov: PCI nic count {len(node_nic_info.get_pci_nics())}")
            assert_that(len(node_nic_info.get_pci_nics())).described_as(
                f"VF count inside VM is {len(node_nic_info.get_pci_nics())}, "
                f"actual sriov nic count is {sriov_count}"
            ).is_equal_to(sriov_count)
