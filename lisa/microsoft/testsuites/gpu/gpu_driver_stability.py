# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Gpu, GpuEnabled, SerialConsole
from lisa.operating_system import BSD, AlmaLinux, Oracle, Suse, Windows
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.tools import Lspci, Reboot
from lisa.tools.gpu_drivers import ComputeSDK, GpuDriver


@TestSuiteMetadata(
    area="gpu",
    category="functional",
    name="GpuDriverStability",
    description="""
    This test suite validates GPU driver stability across reboot cycles.
    It ensures that GPU drivers remain loaded and functional after
    repeated reboots, which is critical for production reliability.
    """,
)
class GpuDriverStability(TestSuite):
    TIMEOUT = 3600
    _REBOOT_ROUNDS = 3

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")

    @TestCaseMetadata(
        description="""
            Verifies GPU driver persistence across multiple consecutive reboots.

            This test validates a real-world reliability concern: GPU drivers
            must remain loaded and report the correct device count after
            the VM is rebooted multiple times.

            Steps:
            1. Install GPU drivers and validate they load correctly.
            2. Record the initial GPU count from lspci and vendor tools.
            3. Reboot the VM multiple times (with panic check).
            4. After each reboot, verify:
               a. GPU PCI devices are still detected.
               b. GPU driver module is loaded.
               c. Vendor monitoring tool (nvidia-smi / rocm-smi) reports
                  the same device count as before reboot.
        """,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            supported_features=[GpuEnabled(), SerialConsole, AzureExtension],
            unsupported_os=[AlmaLinux, Oracle, Suse],
        ),
        priority=2,
    )
    def verify_gpu_driver_persists_across_reboots(
        self,
        node: Node,
        log_path: Path,
        log: Logger,
    ) -> None:
        # Arrange — install driver and record baseline GPU state
        gpu_feature = node.features[Gpu]
        compute_sdk = _get_supported_driver(node)
        gpu_driver: GpuDriver = node.tools.get(GpuDriver, compute_sdk=compute_sdk)

        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)

        lspci_tool = node.tools[Lspci]
        initial_devices = gpu_feature.remove_virtual_gpus(
            lspci_tool.get_gpu_devices(force_run=True)
        )
        initial_gpu_count = len(initial_devices)
        assert_that(initial_gpu_count).described_as(
            "At least one GPU must be present before reboot cycles begin."
        ).is_greater_than(0)

        initial_driver_count = gpu_driver.get_gpu_count()
        log.info(
            f"Baseline: lspci={initial_gpu_count}, " f"driver={initial_driver_count}"
        )

        # Act & Assert — reboot N times and verify after each cycle
        for round_number in range(1, self._REBOOT_ROUNDS + 1):
            log.info(f"Reboot round {round_number}/{self._REBOOT_ROUNDS}")
            reboot_tool.reboot_and_check_panic(log_path)

            # Verify PCI devices survived reboot
            current_devices = gpu_feature.remove_virtual_gpus(
                lspci_tool.get_gpu_devices(force_run=True)
            )
            current_pci_count = len(current_devices)
            assert_that(current_pci_count).described_as(
                f"GPU PCI count changed after reboot round {round_number}. "
                f"Expected {initial_gpu_count}, got {current_pci_count}."
            ).is_equal_to(initial_gpu_count)

            # Verify driver module is still loaded
            assert_that(gpu_feature.is_module_loaded()).described_as(
                f"GPU kernel driver not loaded after reboot round {round_number}."
            ).is_true()

            # Verify vendor tool reports the same count
            current_driver_count = gpu_driver.get_gpu_count()
            assert_that(current_driver_count).described_as(
                f"GPU count from vendor tool changed after reboot round "
                f"{round_number}. Expected {initial_driver_count}, "
                f"got {current_driver_count}."
            ).is_equal_to(initial_driver_count)

            log.info(
                f"Round {round_number} passed: pci={current_pci_count}, "
                f"driver={current_driver_count}"
            )

        log.info(f"GPU driver stability verified across {self._REBOOT_ROUNDS} reboots.")


def _get_supported_driver(node: Node) -> ComputeSDK:
    gpu_feature = node.features[Gpu]
    driver_type = gpu_feature.get_supported_driver()

    if driver_type not in list(ComputeSDK):
        raise SkippedException(f"Unsupported driver type: {driver_type}")

    return driver_type
