# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import Path
from typing import Any, List

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
from lisa.features import Gpu, GpuEnabled
from lisa.operating_system import (
    BSD,
    AlmaLinux,
    Debian,
    Linux,
    Oracle,
    Suse,
    Ubuntu,
    Windows,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.tools import (
    Dmesg,
    Lspci,
    Mkdir,
    Modprobe,
    NvidiaSmi,
    Reboot,
    Service,
    Tar,
    Wget,
)
from lisa.tools.gpu_drivers import ComputeSDK, GpuDriver
from lisa.tools.python import PythonVenv
from lisa.util import LisaException, UnsupportedOperationException, get_matched_str

_cudnn_location = (
    "https://developer.download.nvidia.com/compute/redist/cudnn/"
    "v7.5.0/cudnn-10.0-linux-x64-v7.5.0.56.tgz"
)
_cudnn_file_name = "cudnn.tgz"


@TestSuiteMetadata(
    area="gpu",
    category="functional",
    name="Gpu",
    description="""
    This test suite runs the gpu test cases.
    """,
    requirement=simple_requirement(supported_os=[Linux]),
)
class GpuTestSuite(TestSuite):
    TIMEOUT = 2000

    # Each reset is allowed NvidiaSmi.RESET_TIMEOUT, and the case also has to
    # cover the driver installation, the dmesg checks and the cleanup.
    GPU_RESET_TIMEOUT = 5400

    _pytorch_pattern = re.compile(r"^gpu count: (?P<count>\d+)", re.M)
    _numpy_error_pattern = re.compile(
        "Otherwise reinstall numpy",
        re.M,
    )

    # nvidia-smi reports one of these when the platform does not expose the
    # GPU reset path to the guest, which is a skip rather than a failure.
    _gpu_reset_unsupported_pattern = re.compile(
        r"not supported|Insufficient Permissions|has been deprecated",
        re.IGNORECASE,
    )

    # A CPU soft lockup during GPU reset is timing dependent, so a single
    # reset is not enough to expose it.
    _gpu_reset_iterations = 3

    # These services open /dev/nvidia* and keep the device busy, which makes
    # 'nvidia-smi -r' fail with 'In use by another client'.
    _gpu_holding_services = (
        "nvidia-persistenced",
        "nvidia-fabricmanager",
        "nvidia-dcgm",
    )

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        # Defense-in-depth: catches custom VHD/SIG images whose OS detection
        # may misclassify the node and bypass the supported_os gate.
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")

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
        timeout=TIMEOUT,
        requirement=simple_requirement(
            supported_features=[GpuEnabled(), AzureExtension],
            unsupported_os=[AlmaLinux, Oracle, Suse],
        ),
        priority=1,
    )
    def verify_load_gpu_driver(
        self,
        node: Node,
        log_path: Path,
        log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        _install_driver(node, log_path, log)
        _check_driver_installed(node, log)

    @TestCaseMetadata(
        description="""
            This test case verifies if gpu is detected as PCI device

            Steps:
            1. Boot VM with at least 1 GPU
            2. Verify if GPU is detected as PCI Device
            3. Reboot VM
            4. Verify if PCI GPU device count is same as earlier

        """,
        timeout=TIMEOUT,
        requirement=simple_requirement(min_gpu_count=1),
        priority=1,
    )
    def verify_gpu_provision(self, node: Node, log: Logger) -> None:
        _gpu_provision_check(1, node, log)

    @TestCaseMetadata(
        description="""
            This test case verifies if multiple gpus are detected as PCI devices

            Steps:
            1. Boot VM with multiple GPUs
            2. Verify if GPUs are detected as PCI Devices
            3. Reboot VM
            4. Verify if PCI GPU device count is same as earlier

        """,
        timeout=TIMEOUT,
        # min_gpu_count is 8 since it is current
        # max GPU count available in Azure
        requirement=simple_requirement(min_gpu_count=8),
        priority=3,
    )
    def verify_max_gpu_provision(self, node: Node, log: Logger) -> None:
        _gpu_provision_check(8, node, log)

    @TestCaseMetadata(
        description="""
            This test case verifies if gpu drivers are installed using extension.

            Steps:
            1. Install the GPU Driver using Extension.
            2. Reboot and check for kernel panic
            3. Validate gpu drivers can be loaded successfully.

        """,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            supported_features=[GpuEnabled(), AzureExtension],
            unsupported_os=[AlmaLinux, Oracle, Suse],
        ),
        priority=2,
    )
    def verify_gpu_extension_installation(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        gpu_feature = node.features[Gpu]
        try:
            gpu_feature._install_driver_using_platform_feature()
        except UnsupportedOperationException:
            raise SkippedException(
                "GPU Driver Installation using extension is not supported\n"
                "https://learn.microsoft.com/en-us/azure/virtual-machines/extensions/hpccompute-gpu-linux"  # noqa: E501
            )
        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)
        _check_driver_installed(node, log)

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
        timeout=TIMEOUT,
        requirement=simple_requirement(
            supported_features=[GpuEnabled()],
            unsupported_os=[AlmaLinux, Oracle, Suse],
        ),
        priority=2,
    )
    def verify_gpu_adapter_count(self, node: Node, log_path: Path, log: Logger) -> None:
        _install_driver(node, log_path, log)
        gpu_feature = node.features[Gpu]
        assert isinstance(node.capability.gpu_count, int)
        expected_count = node.capability.gpu_count

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

        _check_driver_installed(node, log)

        vendor_cmd_device_count = gpu_feature.get_gpu_count_with_vendor_cmd()
        assert_that(
            vendor_cmd_device_count,
            "Expected device count didn't match Actual device count"
            " from vendor command",
        ).is_equal_to(expected_count)

    @TestCaseMetadata(
        description="""
        This test case will
        1. Validate disabling GPU devices.
        2. Validate enable back the disabled GPU devices.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[GpuEnabled()],
        ),
    )
    def verify_gpu_rescind_validation(
        self,
        node: Node,
        log_path: Path,
        log: Logger,
    ) -> None:
        lspci = node.tools[Lspci]
        gpu = node.features[Gpu]

        gpu_devices = lspci.get_gpu_devices()
        gpu_devices = gpu.remove_virtual_gpus(gpu_devices)

        # remove nvidia modules to release the GPU devices in used.
        modprobe = node.tools[Modprobe]
        modprobe.remove(["nvidia_drm", "nvidia_uvm", "nvidia_modeset", "nvidia"])

        # 1. Disable GPU devices.
        for device in gpu_devices:
            lspci.disable_device(device)

        # 2. Enable GPU devices.
        lspci.enable_devices()

    @TestCaseMetadata(
        description="""
        This test case verifies that resetting the GPUs does not destabilize
        the guest kernel.

        Steps:
        1. Install the gpu driver and validate it is loaded.
        2. Record the kernel errors already present in dmesg.
        3. Reset all GPUs with nvidia-smi several times.
        4. Validate no new kernel error, such as a CPU soft lockup, a call
            trace or an RCU stall, appeared after each reset.
        5. Validate the gpu count is unchanged and the driver is still healthy.
        """,
        timeout=GPU_RESET_TIMEOUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[GpuEnabled()],
            unsupported_os=[AlmaLinux, Oracle, Suse],
        ),
    )
    def verify_gpu_reset(self, node: Node, log_path: Path, log: Logger) -> None:
        if _get_supported_driver(node) == ComputeSDK.AMD:
            raise SkippedException(
                "GPU reset validation is implemented for NVIDIA GPUs only."
            )

        _install_driver(node, log_path, log)
        _check_driver_installed(node, log)

        gpu = node.features[Gpu]
        expected_count = gpu.get_gpu_count_with_lspci()

        nvidia_smi = node.tools[NvidiaSmi]
        dmesg = node.tools[Dmesg]

        # A reset can leave the device or the driver in a degraded state.
        node.mark_dirty()

        # Populated as services are stopped so a failure midway still restores
        # the ones already stopped.
        stopped_services: List[str] = []
        try:
            self._release_gpu_holders(node, log, stopped_services)

            # Errors already in dmesg, including any logged while unloading the
            # nvidia modules, are not caused by the reset.
            baseline_errors = set(
                dmesg.check_kernel_errors(
                    force_run=True, throw_error=False
                ).splitlines()
            )

            for iteration in range(1, self._gpu_reset_iterations + 1):
                log.info(
                    f"resetting {expected_count} GPUs on {node.name}, gpu reset "
                    f"iteration {iteration} of {self._gpu_reset_iterations}"
                )
                result = nvidia_smi.reset()
                if result.exit_code != 0:
                    output = f"{result.stdout}\n{result.stderr}"
                    if self._gpu_reset_unsupported_pattern.search(output):
                        raise SkippedException(
                            f"GPU reset is not available to the guest on this VM "
                            f"size: {output}"
                        )
                    raise LisaException(
                        f"'nvidia-smi -r' failed with exit code {result.exit_code} "
                        f"on gpu reset iteration {iteration}: {output}. Verify no "
                        f"process is holding a GPU and that the VM size allows a "
                        f"guest initiated reset."
                    )
                log.debug(f"gpu reset iteration {iteration} output: {result.stdout}")

                new_errors = (
                    set(
                        dmesg.check_kernel_errors(
                            force_run=True, throw_error=False
                        ).splitlines()
                    )
                    - baseline_errors
                )
                assert_that(sorted(new_errors)).described_as(
                    f"new kernel errors appeared in dmesg after gpu reset iteration "
                    f"{iteration}; resetting a GPU must not hang or destabilize the "
                    f"guest kernel"
                ).is_empty()
        finally:
            service = node.tools[Service]
            for name in stopped_services:
                # Restoring must not mask the reset failure that got us here.
                # start_service asserts on the exit code, so a failed restart
                # surfaces as an AssertionError.
                try:
                    service.start_service(name)
                except (LisaException, AssertionError) as identifier:
                    log.info(f"could not restart '{name}' after reset: {identifier}")

        actual_count = gpu.get_gpu_count_with_lspci()
        assert_that(actual_count).described_as(
            "gpu count from lspci changed after reset, some GPUs did not come "
            "back on the PCI bus"
        ).is_equal_to(expected_count)

        _check_driver_installed(node, log)

    def _release_gpu_holders(
        self, node: Node, log: Logger, stopped_services: List[str]
    ) -> None:
        service = node.tools[Service]
        for name in self._gpu_holding_services:
            if not service.check_service_exists(name):
                continue
            if not service.is_service_running(name):
                continue
            log.info(f"stopping '{name}' so it does not hold a GPU during reset")
            service.stop_service(name)
            stopped_services.append(name)

        # Idle nvidia_uvm/nvidia_drm still count as clients for 'nvidia-smi -r'.
        node.tools[Modprobe].remove(
            ["nvidia_drm", "nvidia_uvm", "nvidia_modeset"], ignore_error=True
        )

    @TestCaseMetadata(
        description="""
        This test case will run PyTorch to check CUDA driver installed correctly.

        1. Install PyTorch.
        2. Check GPU count by torch.cuda.device_count()
        3. Compare with PCI result
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[GpuEnabled()],
            unsupported_os=[AlmaLinux, Oracle, Suse],
        ),
    )
    def verify_gpu_cuda_with_pytorch(
        self,
        node: Node,
        log_path: Path,
        log: Logger,
    ) -> None:
        _install_driver(node, log_path, log)
        _check_driver_installed(node, log)

        # Step 1, pytorch/CUDA needs 8GB to download & install, increase to 20GB
        torch_required_space = 20
        work_path = node.get_working_path_with_required_space(torch_required_space)

        # Step 2, Install cudnn and pyTorch
        _install_cudnn(node, log, work_path)
        pythonvenv_path = work_path + "/gpu_pytorch"
        pythonvenv = node.tools.create(PythonVenv, venv_path=pythonvenv_path)

        # Pip downloads .whl and other tmp files to root disk.
        # Clean package cache to avoid disk full issue.
        if isinstance(node.os, Linux):
            node.os.clean_package_cache()

        pythonvenv.install_packages("torch")

        # Step 3, verification
        gpu = node.features[Gpu]
        gpu_script = "import torch;print(f'gpu count: {torch.cuda.device_count()}')"
        expected_count = gpu.get_gpu_count_with_lspci()

        script_result = pythonvenv.run(
            f'-c "{gpu_script}"',
            force_run=True,
        )

        if script_result.exit_code != 0 and self._numpy_error_pattern.findall(
            script_result.stdout
        ):
            if pythonvenv.uninstall_package("numpy"):
                pythonvenv.install_packages("numpy")
            script_result = pythonvenv.run(
                f'-c "{gpu_script}"',
                force_run=True,
            )

        gpu_count_str = get_matched_str(script_result.stdout, self._pytorch_pattern)
        script_result.assert_exit_code(
            message=f"failed on run gpu script: {gpu_script}, "
            f"output: {script_result.stdout}"
        )

        assert_that(gpu_count_str).described_as(
            f"gpu count is not in result: {script_result.stdout}"
        ).is_not_empty()

        gpu_count = int(gpu_count_str)
        assert_that(gpu_count).described_as(
            "GPU must be greater than zero."
        ).is_greater_than(0)
        assert_that(gpu_count).described_as(
            "cannot detect GPU from PyTorch"
        ).is_equal_to(expected_count)


def _check_driver_installed(node: Node, log: Logger) -> None:
    gpu = node.features[Gpu]
    lspci_gpucount = gpu.get_gpu_count_with_lspci()

    compute_sdk = _get_supported_driver(node)

    gpu_driver: GpuDriver = node.tools.get(GpuDriver, compute_sdk=compute_sdk)
    driver_gpucount = gpu_driver.get_gpu_count()

    assert_that(lspci_gpucount).described_as(
        f"GPU count from lspci ({lspci_gpucount}) not equal to "
        f"count from GPU monitoring tool ({driver_gpucount})"
    ).is_equal_to(driver_gpucount)

    log.info(f"GPU driver validated successfully with {driver_gpucount} GPUs")


# TODO: Move 'get_supported_driver' to GpuDriver, it should detect the
# device and driver using lspci instead of relying on the GPU feature.
def _get_supported_driver(node: Node) -> ComputeSDK:
    gpu_feature = node.features[Gpu]
    driver_type = gpu_feature.get_supported_driver()

    if driver_type not in list(ComputeSDK):
        raise SkippedException(f"Unsupported driver type: {driver_type}")

    return driver_type


def _install_cudnn(node: Node, log: Logger, install_path: str) -> None:
    wget = node.tools[Wget]

    path = wget.get_tool_path(use_global=True)
    if node.shell.exists(path / _cudnn_file_name):
        return

    work_path = install_path + "/cudnn"
    node.tools[Mkdir].create_directory(work_path)

    log.debug(f"CUDNN Extracted path is: {work_path}  ")
    download_path = wget.get(
        url=_cudnn_location, filename=str(_cudnn_file_name), file_path=work_path
    )

    node.tools[Tar].extract(download_path, work_path)

    if isinstance(node.os, Debian):
        target_path = "/usr/lib/x86_64-linux-gnu/"
    else:
        target_path = "/usr/lib64/"
    node.execute(
        f"cp -p {work_path}/cuda/lib64/libcudnn* {target_path}",
        shell=True,
        sudo=True,
    )
    return


def _install_driver(node: Node, log_path: Path, log: Logger) -> None:
    """
    Install GPU driver using either Azure extension or direct driver tools.

    This function attempts to install the driver in the following order:
    1. Try Azure GPU Extension (platform-specific)
    2. Fall back to direct driver installation via tools

    The driver type is determined by the Gpu feature based on VM SKU.
    """
    gpu_feature = node.features[Gpu]
    if gpu_feature.is_module_loaded():
        return

    if isinstance(node.os, Ubuntu):
        sources_before = node.execute(
            "ls -A1 /etc/apt/sources.list.d", sudo=True
        ).stdout.split("\n")

    # Try to install GPU driver using extension
    try:
        gpu_feature._install_driver_using_platform_feature()
        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)
        return
    except UnsupportedOperationException:
        log.info("Installing Driver using Azure GPU Extension is not supported")
    except Exception:
        log.info("Failed to install Driver using Azure GPU Extension")
        if isinstance(node.os, Ubuntu):
            # Cleanup required because extension might add sources
            sources_after = node.execute(
                "ls -A1 /etc/apt/sources.list.d", sudo=True
            ).stdout.split("\n")
            __remove_sources_added_by_extension(node, sources_before, sources_after)

    __install_driver_using_sdk(node, log, log_path)


def _gpu_provision_check(min_pci_count: int, node: Node, log: Logger) -> None:
    lspci = node.tools[Lspci]

    init_gpu = lspci.get_gpu_devices(force_run=True)
    log.debug(f"Initial GPU count {len(init_gpu)}")
    assert_that(len(init_gpu)).described_as(
        f"Detected GPU PCI device count {len(init_gpu)} is less than the "
        f"expected minimum {min_pci_count}"
    ).is_greater_than_or_equal_to(min_pci_count)

    node.reboot()

    curr_gpu = lspci.get_gpu_devices(force_run=True)
    log.debug(f"GPU count after reboot {len(curr_gpu)}")
    assert_that(len(curr_gpu)).described_as(
        "GPU PCI device count should be same after reboot"
    ).is_equal_to(len(init_gpu))


def __remove_sources_added_by_extension(
    node: Node, sources_before: List[str], sources_after: List[str]
) -> None:
    rm_sources = [source for source in sources_after if source not in sources_before]
    for source in rm_sources:
        node.execute(f"rm /etc/apt/sources.list.d/{source}", sudo=True)


def __install_driver_using_sdk(node: Node, log: Logger, log_path: Path) -> None:
    """
    Install GPU driver using appropriate driver tool based on supported driver type.

    This function:
    1. Installs LIS driver if required (for older kernels)
    2. Determines which driver type is supported (GRID, CUDA, or AMD)
    3. Installs the appropriate driver using the corresponding tool
    4. Reboots to load the driver
    """
    # Install LIS driver if required (for older kernels)
    try:
        from lisa.tools import LisDriver

        node.tools[LisDriver]
    except Exception as e:
        log.debug(f"LisDriver is not installed. It might not be required. {e}")

    compute_sdk = _get_supported_driver(node)
    _ = node.tools.get(GpuDriver, compute_sdk=compute_sdk)

    log.debug("GPU driver installed. Rebooting to load driver.")
    reboot_tool = node.tools[Reboot]
    reboot_tool.reboot_and_check_panic(log_path)
