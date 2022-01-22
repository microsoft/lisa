# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path

from assertpy import assert_that

from lisa import (
    LisaException,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    constants,
    simple_requirement,
)
from lisa.features import Gpu, SerialConsole
from lisa.tools import Lspci, Reboot


@TestSuiteMetadata(
    area="gpu",
    category="functional",
    name="Gpu",
    description="""
    This test suite runs the gpu test cases.
    """,
)
class GpuTestSuite(TestSuite):
    def _ensure_driver_installed(
        self, node: Node, gpu_feature: Gpu, log_path: Path, log: Logger
    ) -> None:
        if gpu_feature.is_module_loaded():
            return

        gpu_feature.install_compute_sdk()
        log.debug(
            f"{gpu_feature.gpu_vendor} sdk installed. Will reboot to load driver."
        )

        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)

        if not gpu_feature.is_module_loaded():
            raise LisaException(
                f"{gpu_feature.gpu_vendor} GPU driver is not loaded after VM restart!"
            )

    @TestCaseMetadata(
        description="""
            This test case verifies if gpu drivers are loaded fine.

            Steps:
            1. Validate if the VM SKU is supported for GPU.
            2. Install LIS drivers if not already installed for Fedora and its
                derived distros. Reboot the node
            3. Install required gpu drivers on the VM and reboot the node. Validate gpu
                drivers can be loaded successfully.

        """,
        requirement=simple_requirement(
            supported_features=[Gpu, SerialConsole],
        ),
        priority=1,
    )
    def validate_load_gpu_driver(self, node: Node, log_path: Path, log: Logger) -> None:
        gpu_feature = node.features[Gpu]
        if not gpu_feature.is_supported():
            raise SkippedException(f"GPU is not supported with distro {node.os}")

        self._ensure_driver_installed(node, gpu_feature, log_path, log)

    @TestCaseMetadata(
        description="""
            This test case verifies the gpu adapter count.

            Steps:
            1. Assert that node supports GPU.
            2. If GPU modules are not loaded, install and load the module first.
            3. Find the expected gpu count for the node.
            4. Validate expected and actual gpu count using lsvmbus output.
            5. Validate expected and actual gpu count using lspci output.
            6. Validate expected and actual gpu count using gpu vendor commands
                 example - nvidia-smi
        """,
        requirement=simple_requirement(
            supported_features=[Gpu],
        ),
        priority=2,
    )
    def validate_gpu_adapter_count(self, node: Node) -> None:
        gpu_feature = node.features[Gpu]
        if not gpu_feature.is_supported():
            raise SkippedException(f"GPU is not supported with distro {node.os}")

        assert isinstance(node.capability.gpu_count, int)
        expected_count = node.capability.gpu_count

        gpu_feature = node.features[Gpu]
        lsvmbus_device_count = gpu_feature.get_gpu_count_with_lsvmbus()
        assert_that(
            lsvmbus_device_count,
            "Expected device count didn't match Actual device count from lsvmbus",
        ).is_equal_to(expected_count)

        lspci_device_count = gpu_feature.get_gpu_count_with_lspci()
        assert_that(
            lspci_device_count,
            "Expected device count didn't match Actual device count from lspci",
        ).is_equal_to(expected_count)

        vendor_cmd_device_count = gpu_feature.get_gpu_count_with_vendor_cmd()
        assert_that(
            vendor_cmd_device_count,
            "Expected device count didn't match Actual device count"
            "from vendor command",
        ).is_equal_to(expected_count)

    @TestCaseMetadata(
        description="""
        This test case will
        1. Validate disabling GPU devices.
        2. Validate enable back the disabled GPU devices.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[Gpu],
        ),
    )
    def gpu_rescind_validation(self, node: Node) -> None:
        lspci = node.tools[Lspci]
        # 1. Disable GPU devices.
        lspci.disable_devices(device_type=constants.DEVICE_TYPE_GPU)
        # 2. Enable GPU devices.
        lspci.enable_devices()
