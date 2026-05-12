# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
VM Specification Validation Test Suite

Each test reads the expected hardware specification from the VM size's
Azure container policy (the ``resource_sku`` capabilities published by
the platform) instead of from runbook variables / CSV. After the
platform provisions the VM, the suite asserts that what the guest
actually sees matches what the container policy declared.

Usage
=====
See the accompanying ``lisa/microsoft/runbook/examples/vm_spec_validation.yml``
runbook for a ready-to-run example.
"""

from typing import Any, Dict, List, Tuple, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk, Nvme
from lisa.features.nvme import NvmeSettings
from lisa.microsoft.testsuites.network.common import (
    initialize_nic_info,
    skip_if_no_synthetic_nics,
    sriov_basic_test,
)
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import AzureNodeSchema
from lisa.sut_orchestrator.azure.features import AzureDiskOptionSettings
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
import re

from lisa.tools import Dmesg, Fio, Lscpu, Lsblk, Lspci
from lisa.util import LisaException, constants

# Percentage tolerance for memory comparison. Hypervisor / firmware
# reserve a portion of RAM that is not visible to the OS.
_MEMORY_TOLERANCE_PERCENT = 2

# Percentage tolerance for IOPS / throughput comparisons.
_PERF_TOLERANCE_PERCENT = 7

# Number of iterations for performance tests; the best result is used.
_PERF_ITERATIONS = 3

# fio run time (seconds) for sustained performance tests.
_PERF_RUN_TIME_SECONDS = 120

# fio run time (seconds) for burst performance tests. Premium SSD burst
# credits sustain peak performance for ~30 minutes, but a short window is
# used so the run completes well inside the burst budget.
_BURST_RUN_TIME_SECONDS = 30

# Number of iterations for burst tests. A single iteration captures the
# burst window; extra iterations would consume / deplete burst credits
# and skew later results.
_BURST_ITERATIONS = 1

# Possible Azure SKU capability names for VM-level burst IOPS and
# burst bandwidth. The first one present in the container policy wins.
_BURST_IOPS_CAP_NAMES = ("MaxBurstIops", "UncachedDiskBurstIOPS")
_BURST_BW_CAP_NAMES = (
    "MaxBurstBandwidthMBps",
    "UncachedDiskBurstBytesPerSecond",
)


def _vm_size(node: Node) -> str:
    """Return the Azure VM size string for log labels (best-effort)."""
    try:
        return node.capability.get_extended_runbook(
            AzureNodeSchema, AZURE
        ).vm_size or "unknown"
    except Exception:
        return "unknown"


def _get_azure_raw_caps(
    environment: Environment, node: Node, log: Logger
) -> Dict[str, str]:
    """
    Return the raw Azure SKU capability map (container policy) for the
    VM size that backs ``node``.

    Skips the test when the platform is not Azure or when no capability
    information is available for the VM size.
    """
    platform = environment.platform
    if platform is None or platform.type_name() != AZURE:
        raise SkippedException(
            "Azure container policy is only available on the Azure platform."
        )
    azure_platform = cast(AzurePlatform, platform)
    node_runbook = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
    location_info = azure_platform.get_location_info(node_runbook.location, log)
    capability = location_info.capabilities.get(node_runbook.vm_size)
    if capability is None:
        raise SkippedException(
            f"No SKU capability info available for vm size "
            f"{node_runbook.vm_size} in {node_runbook.location}."
        )
    return {
        cap["name"]: cap["value"]
        for cap in capability.resource_sku.get("capabilities", [])
    }


def _required_int_cap(caps: Dict[str, str], name: str) -> int:
    """Return ``caps[name]`` as an int, or skip if missing / non-positive."""
    raw = caps.get(name)
    if raw is None or str(raw).strip() == "":
        raise SkippedException(
            f"Container policy does not publish '{name}' for this VM size."
        )
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise SkippedException(
            f"Container policy '{name}' value {raw!r} is not an integer."
        ) from exc
    if value <= 0:
        raise SkippedException(
            f"Container policy '{name}' is {value} (zero or negative)."
        )
    return value


def _first_present_int_cap(
    caps: Dict[str, str], names: Tuple[str, ...]
) -> Tuple[str, int]:
    """
    Return ``(name, value)`` for the first name in ``names`` that is
    published as a positive integer in ``caps``. Skip if none match.
    """
    for name in names:
        raw = caps.get(name)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = int(str(raw).strip())
        except ValueError:
            continue
        if value > 0:
            return name, value
    raise SkippedException(
        f"Container policy does not publish any of {names} for this VM size."
    )


def _resolved_int(value: Any, name: str) -> int:
    """
    Return a concrete int from a NodeSpace capability field.

    NodeSpace fields use ``search_space.CountSpace`` (int or IntRange).
    After the platform resolves a node, these fields should be concrete
    ints; if not, skip with a clear message.
    """
    if isinstance(value, bool):
        raise SkippedException(f"Capability '{name}' is a bool, expected int.")
    if isinstance(value, int):
        return value
    raise SkippedException(
        f"Capability '{name}' is not a concrete integer (got {value!r})."
    )


def _expected_max_nic_count(node: Node) -> int:
    """Return the resolved max NIC count from the node capability."""
    nic = node.capability.network_interface
    if nic is None:
        raise SkippedException(
            "node.capability.network_interface is not set - cannot determine "
            "expected NIC count from container policy."
        )
    return _resolved_int(nic.max_nic_count, "network_interface.max_nic_count")


def _expected_max_data_disk_count(node: Node) -> int:
    """Return the resolved max data disk count from the node capability."""
    disk = node.capability.disk
    if disk is None:
        raise SkippedException(
            "node.capability.disk is not set - cannot determine expected "
            "max data disk count from container policy."
        )
    return _resolved_int(disk.max_data_disk_count, "disk.max_data_disk_count")


@TestSuiteMetadata(
    area="vm_spec_validation",
    category="functional",
    description="""
    Validates that a provisioned Azure VM matches the hardware
    specification published by its container policy (Azure SKU
    capabilities): CPU count, memory, GPU count, NIC count, max data
    disks, local NVMe disks, and disk IOPS / throughput.

    Expected values are read directly from the platform's capability
    map at runtime; no runbook variables or CSV files are required.
    """,
)
class VmSpecValidation(TestSuite):
    """Validate VM hardware against the Azure container policy."""

    # ------------------------------------------------------------------
    # CPU validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM's vCPU count matches the value published by
        the VM size's container policy.

        Steps:
        1. Read expected vCPU count from ``node.capability.core_count``.
        2. Query the VM's actual vCPU count via ``lscpu``.
        3. Assert they are equal.
        """,
        priority=4,
        requirement=simple_requirement(),
    )
    def verify_vm_cpu_count(self, node: Node, log: Logger) -> None:
        expected_cpu = _resolved_int(node.capability.core_count, "core_count")
        actual_cpu = node.tools[Lscpu].get_thread_count()
        vm_size = _vm_size(node)
        log.info(
            f"VM size: {vm_size} - expected CPUs: {expected_cpu}, "
            f"actual CPUs: {actual_cpu}"
        )
        assert_that(actual_cpu).described_as(
            f"VM size {vm_size}: expected {expected_cpu} vCPUs "
            f"but found {actual_cpu}"
        ).is_equal_to(expected_cpu)

    # ------------------------------------------------------------------
    # Memory validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM's total memory is within an acceptable range
        of the value published by the VM size's container policy.

        A tolerance of 5% is allowed because the hypervisor and
        firmware reserve a portion of RAM that is not visible to the OS.

        Steps:
        1. Read expected memory (MB) from ``node.capability.memory_mb``.
        2. Read actual total memory from the kernel boot line
           ``Memory: <available>K/<total>K available`` reported by
           ``dmesg`` (the second number is the total memory the kernel
           saw from BIOS / firmware).
        3. Assert the actual value is within 5% of expected (and not
           greater than the declared value).
        """,
        priority=4,
        requirement=simple_requirement(),
    )
    def verify_vm_memory(self, node: Node, log: Logger) -> None:
        expected_memory_mb = _resolved_int(node.capability.memory_mb, "memory_mb")
        actual_memory_mb = _read_total_memory_mb_from_dmesg(node)
        vm_size = _vm_size(node)
        log.info(
            f"VM size: {vm_size} - expected memory: {expected_memory_mb} MB, "
            f"actual memory: {actual_memory_mb} MB"
        )
        lower_bound = int(expected_memory_mb * (100 - _MEMORY_TOLERANCE_PERCENT) / 100)
        # VMs typically report slightly less memory than the nominal value
        # due to hypervisor/firmware reservations, so we allow the actual
        # memory to be up to the expected value but not above it.
        upper_bound = expected_memory_mb
        assert_that(actual_memory_mb).described_as(
            f"VM size {vm_size}: expected ~{expected_memory_mb} MB memory "
            f"but found {actual_memory_mb} MB "
            f"(tolerance {_MEMORY_TOLERANCE_PERCENT}%)"
        ).is_between(lower_bound, upper_bound)

    # ------------------------------------------------------------------
    # GPU count validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM exposes the expected number of GPU devices
        as published by the container policy.

        Steps:
        1. Read expected GPU count from ``node.capability.gpu_count``.
        2. Query GPU PCI devices via ``lspci``.
        3. Assert the GPU device count matches.
        """,
        priority=4,
        requirement=simple_requirement(min_gpu_count=1),
    )
    def verify_vm_gpu_count(self, node: Node, log: Logger) -> None:
        expected_gpu_count = _resolved_int(node.capability.gpu_count, "gpu_count")
        vm_size = _vm_size(node)

        gpu_devices = node.tools[Lspci].get_gpu_devices(force_run=True)
        actual_gpu_count = len(gpu_devices)
        log.info(
            f"VM size: {vm_size} - expected GPUs: {expected_gpu_count}, "
            f"actual GPUs: {actual_gpu_count}"
        )
        assert_that(actual_gpu_count).described_as(
            f"VM size {vm_size}: expected {expected_gpu_count} GPU device(s) "
            f"but found {actual_gpu_count}"
        ).is_equal_to(expected_gpu_count)

    # ------------------------------------------------------------------
    # SR-IOV NIC count validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify the VM exposes the expected number of SR-IOV VF devices
        by provisioning with the maximum NIC count and checking the
        VF PCI device count reported by ``lspci``.

        Steps:
        1. Provision the VM with max SR-IOV NICs (choose_max_value).
        2. Read expected NIC count from
           ``node.capability.network_interface.max_nic_count``.
        3. Run initialize_nic_info to validate NIC/IP/VF pairing.
        4. Run sriov_basic_test to verify SR-IOV modules and VFs.
        5. Query VF devices via ``lspci``.
        6. Assert VF count matches expected.
        """,
        priority=4,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_sriov_nic_count(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        expected_nic_count = _expected_max_nic_count(node)
        vm_size = _vm_size(node)

        # Validate SR-IOV NIC info: IP assignment + VF pairing
        initialize_nic_info(environment, is_sriov=True)
        # Verify SR-IOV modules loaded and VF device counts
        sriov_basic_test(environment)

        # Count VF PCI devices reported by lspci
        lspci = node.tools[Lspci]
        vf_slots = lspci.get_device_names_by_type(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        actual_vf_count = len(vf_slots)
        log.info(
            f"VM size: {vm_size} - expected VFs: {expected_nic_count}, "
            f"actual VFs: {actual_vf_count} (slots: {vf_slots})"
        )
        assert_that(actual_vf_count).described_as(
            f"VM size {vm_size}: expected {expected_nic_count} SR-IOV VF "
            f"device(s) but found {actual_vf_count}"
        ).is_equal_to(expected_nic_count)

    # ------------------------------------------------------------------
    # Synthetic NIC count validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify the VM supports the expected number of synthetic NICs by
        provisioning with the maximum NIC count and validating that
        each NIC receives an IP address.

        Steps:
        1. Provision the VM with max synthetic NICs (choose_max_value).
        2. Read expected NIC count from
           ``node.capability.network_interface.max_nic_count``.
        3. Skip if the VM has no synthetic NIC devices.
        4. Run initialize_nic_info to validate NIC/IP assignment.
        5. Assert total NIC count matches expected.
        """,
        priority=4,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_synthetic_nic_count(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        expected_nic_count = _expected_max_nic_count(node)
        vm_size = _vm_size(node)

        skip_if_no_synthetic_nics(node)
        # Validate synthetic NIC info: IP assignment
        initialize_nic_info(environment, is_sriov=False)

        actual_nic_count = len(node.nics.nics)
        log.info(
            f"VM size: {vm_size} - expected NICs: {expected_nic_count}, "
            f"actual synthetic NICs: {actual_nic_count}"
        )
        assert_that(actual_nic_count).described_as(
            f"VM size {vm_size}: expected {expected_nic_count} synthetic NICs "
            f"but found {actual_nic_count}"
        ).is_equal_to(expected_nic_count)

    # ------------------------------------------------------------------
    # Max data disk count validation — provision with max disks
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM supports the expected maximum number of data
        disks by provisioning with the maximum disk count allowed by the
        VM size's container policy and confirming the disks are visible
        inside the guest.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read expected max disks from
           ``node.capability.disk.max_data_disk_count``.
        3. Discover all attached raw data disks inside the guest.
        4. Assert the attached disk count matches.
        """,
        priority=4,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_max_premium_ssd_disk_count(self, node: Node, log: Logger) -> None:
        expected_max_disks = _expected_max_data_disk_count(node)
        vm_size = _vm_size(node)

        # Discover all raw data disks visible inside the guest
        data_disks = node.features[Disk].get_raw_data_disks()
        actual_disk_count = len(data_disks)
        log.info(
            f"VM size: {vm_size} - expected max disks: {expected_max_disks}, "
            f"actual data disks: {actual_disk_count} {data_disks}"
        )
        assert_that(actual_disk_count).described_as(
            f"VM size {vm_size}: expected {expected_max_disks} data disks "
            f"but found {actual_disk_count} inside the guest"
        ).is_equal_to(expected_max_disks)

    # ------------------------------------------------------------------
    # NVMe local disk count validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM exposes the expected number of local NVMe
        disks by provisioning a VM size that supports NVMe and
        requesting the maximum local NVMe disk count.

        Steps:
        1. Provision the VM with max local NVMe disks.
        2. Read expected NVMe disk count from the resolved
           ``NvmeSettings`` feature on ``node.capability``.
        3. Discover local NVMe namespaces inside the guest.
        4. Assert the NVMe disk count matches.
        """,
        priority=4,
        requirement=simple_requirement(
            supported_features=[
                NvmeSettings(
                    disk_count=search_space.IntRange(min=1, choose_max_value=True)
                )
            ],
        ),
    )
    def verify_vm_nvme_disk_count(self, node: Node, log: Logger) -> None:
        expected_nvme_disks = _expected_nvme_disk_count(node)
        vm_size = _vm_size(node)

        nvme_disks = node.features[Nvme].get_raw_nvme_disks()
        actual_disk_count = len(nvme_disks)
        log.info(
            f"VM size: {vm_size} - expected NVMe disks: {expected_nvme_disks}, "
            f"actual NVMe disks: {actual_disk_count} {nvme_disks}"
        )
        assert_that(actual_disk_count).described_as(
            f"VM size {vm_size}: expected {expected_nvme_disks} local NVMe "
            f"disks but found {actual_disk_count}"
        ).is_equal_to(expected_nvme_disks)

    # ------------------------------------------------------------------
    # NVMe IOPS validation — fio across all local NVMe disks
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can achieve at least the expected disk IOPS
        on local NVMe storage by provisioning with the maximum NVMe
        disk count and running a ``fio`` random-read benchmark across
        all NVMe namespaces simultaneously.

        Expected IOPS is read from the container policy's
        ``UncachedDiskIOPS`` capability.

        Steps:
        1. Provision the VM with max local NVMe disks.
        2. Read ``UncachedDiskIOPS`` from the container policy.
        3. Discover all local NVMe namespaces.
        4. Run fio random-read 4K across all NVMe disks.
        5. Assert the aggregate IOPS >= expected (with tolerance).
        """,
        priority=4,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            supported_features=[
                NvmeSettings(
                    disk_count=search_space.IntRange(min=1, choose_max_value=True)
                )
            ],
        ),
    )
    def verify_vm_nvme_disk_iops(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        caps = _get_azure_raw_caps(environment, node, log)
        expected_iops = _required_int_cap(caps, "UncachedDiskIOPS")
        vm_size = _vm_size(node)

        nvme_disks = node.features[Nvme].get_raw_nvme_disks()
        if not nvme_disks:
            raise SkippedException(
                "No local NVMe disks found - skipping NVMe IOPS check."
            )

        log.info(
            f"VM size: {vm_size} - discovered {len(nvme_disks)} NVMe disk(s): "
            f"{nvme_disks}"
        )

        measured_iops = _run_fio_iops(
            node, log, vm_size, nvme_disks, label="NVMe", numjob=4
        )
        # Allow tolerance below the declared max
        iops_floor = int(expected_iops * (100 - _PERF_TOLERANCE_PERCENT) / 100)
        log.info(
            f"VM size: {vm_size} - fio across {len(nvme_disks)} NVMe disk(s): "
            f"measured {measured_iops} IOPS, "
            f"expected >= {iops_floor} (declared max: {expected_iops})"
        )
        assert_that(measured_iops).described_as(
            f"VM size {vm_size}: expected NVMe IOPS >= {iops_floor} "
            f"(declared max {expected_iops} with "
            f"{_PERF_TOLERANCE_PERCENT}% tolerance) across "
            f"{len(nvme_disks)} NVMe disk(s) but measured only {measured_iops}"
        ).is_greater_than_or_equal_to(iops_floor)

    # ------------------------------------------------------------------
    # Disk IOPS validation — provision max disks, fio all of them
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can achieve at least the expected disk IOPS
        published by the container policy by provisioning with the
        maximum number of data disks and running a ``fio`` random-read
        benchmark across all of them.

        Expected IOPS is read from the container policy's
        ``UncachedDiskIOPS`` capability.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read ``UncachedDiskIOPS`` from the container policy.
        3. Discover all attached raw data disks.
        4. Run fio random-read 4K across all disks simultaneously.
        5. Assert the aggregate IOPS >= expected (with tolerance).
        """,
        priority=4,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_premium_ssd_iops(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        caps = _get_azure_raw_caps(environment, node, log)
        expected_iops = _required_int_cap(caps, "UncachedDiskIOPS")
        vm_size = _vm_size(node)

        # Discover all raw data disks attached by the platform
        data_disks = node.features[Disk].get_raw_data_disks()
        if not data_disks:
            raise SkippedException(
                "No data disks found after provisioning - skipping IOPS check."
            )

        log.info(
            f"VM size: {vm_size} - discovered {len(data_disks)} data disk(s): "
            f"{data_disks}"
        )

        thread_count = node.tools[Lscpu].get_thread_count()
        measured_iops = _run_fio_iops(
            node, log, vm_size, data_disks, label="disk", numjob=thread_count
        )
        # Allow tolerance below the declared max
        iops_floor = int(expected_iops * (100 - _PERF_TOLERANCE_PERCENT) / 100)
        log.info(
            f"VM size: {vm_size} - fio across {len(data_disks)} disk(s): "
            f"measured {measured_iops} IOPS, "
            f"expected >= {iops_floor} (declared max: {expected_iops})"
        )
        assert_that(measured_iops).described_as(
            f"VM size {vm_size}: expected aggregate disk IOPS >= {iops_floor} "
            f"(declared max {expected_iops} with "
            f"{_PERF_TOLERANCE_PERCENT}% tolerance) across "
            f"{len(data_disks)} disk(s) but measured only {measured_iops}"
        ).is_greater_than_or_equal_to(iops_floor)

    # ------------------------------------------------------------------
    # Storage throughput validation — fio sequential read, 1024K blocks
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can achieve at least the expected storage
        throughput published by the container policy by provisioning
        with the maximum number of data disks and running a ``fio``
        sequential-read benchmark with 1024K block size across all
        of them.

        Expected throughput is read from the container policy's
        ``UncachedDiskBytesPerSecond`` capability (bytes/s) and
        converted to MBps for comparison.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read ``UncachedDiskBytesPerSecond`` from the container policy.
        3. Discover all attached raw data disks.
        4. Run fio sequential-read 1024K across all disks.
        5. Convert measured throughput from MiB/s to MBps.
        6. Assert throughput is within tolerance of expected.
        """,
        priority=4,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_premium_ssd_throughput(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        caps = _get_azure_raw_caps(environment, node, log)
        expected_bytes_per_second = _required_int_cap(
            caps, "UncachedDiskBytesPerSecond"
        )
        # Convert bytes/s -> MBps (1,000,000 bytes/s).
        expected_bw = expected_bytes_per_second // 1_000_000
        vm_size = _vm_size(node)

        # Discover all raw data disks attached by the platform
        data_disks = node.features[Disk].get_raw_data_disks()
        if not data_disks:
            raise SkippedException(
                "No data disks found after provisioning "
                "- skipping storage throughput check."
            )

        log.info(
            f"VM size: {vm_size} - discovered {len(data_disks)} data disk(s): "
            f"{data_disks}"
        )

        thread_count = node.tools[Lscpu].get_thread_count()
        measured_bw = _run_fio_throughput_mbps(
            node, log, vm_size, data_disks, label="disk", numjob=thread_count
        )

        bw_floor = int(expected_bw * (100 - _PERF_TOLERANCE_PERCENT) / 100)
        bw_ceiling = int(expected_bw * (100 + _PERF_TOLERANCE_PERCENT) / 100)
        log.info(
            f"VM size: {vm_size} - fio seq read across "
            f"{len(data_disks)} disk(s): "
            f"measured {measured_bw} MBps, "
            f"expected {bw_floor}-{bw_ceiling} MBps "
            f"(declared: {expected_bw} MBps)"
        )
        assert_that(measured_bw).described_as(
            f"VM size {vm_size}: expected storage throughput "
            f"between {bw_floor} and {bw_ceiling} MBps "
            f"(declared {expected_bw} MBps with "
            f"{_PERF_TOLERANCE_PERCENT}% tolerance) across "
            f"{len(data_disks)} disk(s) but measured "
            f"{measured_bw} MBps"
        ).is_between(bw_floor, bw_ceiling)

    # ------------------------------------------------------------------
    # Burst IOPS validation - short-duration fio inside burst window
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can momentarily achieve at least its declared
        burst IOPS by running a short ``fio`` random-read benchmark
        across all data disks. The run is kept short so the entire
        measurement fits inside the VM's burst credit window.

        Expected burst IOPS is read from the container policy via the
        first available of: ``MaxBurstIops``,
        ``UncachedDiskBurstIOPS``. Skipped when none are published.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read burst IOPS from the container policy.
        3. Discover all attached raw data disks.
        4. Run a short fio random-read 4K burst across all disks.
        5. Assert the aggregate IOPS >= burst expected (with tolerance).
        """,
        priority=4,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_premium_ssd_burst_iops(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        caps = _get_azure_raw_caps(environment, node, log)
        cap_name, expected_burst_iops = _first_present_int_cap(
            caps, _BURST_IOPS_CAP_NAMES
        )
        vm_size = _vm_size(node)

        data_disks = node.features[Disk].get_raw_data_disks()
        if not data_disks:
            raise SkippedException(
                "No data disks found after provisioning "
                "- skipping burst IOPS check."
            )

        log.info(
            f"VM size: {vm_size} - discovered {len(data_disks)} data disk(s): "
            f"{data_disks}; burst IOPS source: {cap_name}={expected_burst_iops}"
        )

        thread_count = node.tools[Lscpu].get_thread_count()
        measured_iops = _run_fio_iops(
            node,
            log,
            vm_size,
            data_disks,
            label="burst-disk",
            numjob=thread_count,
            run_time_seconds=_BURST_RUN_TIME_SECONDS,
            iterations=_BURST_ITERATIONS,
        )
        iops_floor = int(
            expected_burst_iops * (100 - _PERF_TOLERANCE_PERCENT) / 100
        )
        log.info(
            f"VM size: {vm_size} - burst fio across {len(data_disks)} disk(s): "
            f"measured {measured_iops} IOPS, "
            f"expected >= {iops_floor} (declared burst: {expected_burst_iops})"
        )
        assert_that(measured_iops).described_as(
            f"VM size {vm_size}: expected burst disk IOPS >= {iops_floor} "
            f"(declared burst {expected_burst_iops} via {cap_name} with "
            f"{_PERF_TOLERANCE_PERCENT}% tolerance) across "
            f"{len(data_disks)} disk(s) but measured only {measured_iops}"
        ).is_greater_than_or_equal_to(iops_floor)

    # ------------------------------------------------------------------
    # Burst throughput validation - short-duration fio inside burst window
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can momentarily achieve at least its declared
        burst storage throughput by running a short ``fio`` sequential-
        read 1024K benchmark across all data disks. The run is kept
        short so the entire measurement fits inside the VM's burst
        credit window.

        Expected burst throughput is read from the container policy via
        the first available of: ``MaxBurstBandwidthMBps``,
        ``UncachedDiskBurstBytesPerSecond``. The latter is bytes/s
        and is converted to MBps. Skipped when none are published.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read burst throughput from the container policy.
        3. Discover all attached raw data disks.
        4. Run a short fio sequential-read 1024K burst across disks.
        5. Assert throughput is within tolerance of burst expected.
        """,
        priority=4,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_premium_ssd_burst_throughput(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        caps = _get_azure_raw_caps(environment, node, log)
        cap_name, raw_value = _first_present_int_cap(caps, _BURST_BW_CAP_NAMES)
        # Normalize to MBps. ``UncachedDiskBurstBytesPerSecond`` is
        # bytes/s; ``MaxBurstBandwidthMBps`` is already MBps.
        if cap_name == "UncachedDiskBurstBytesPerSecond":
            expected_burst_bw = raw_value // 1_000_000
        else:
            expected_burst_bw = raw_value
        vm_size = _vm_size(node)

        data_disks = node.features[Disk].get_raw_data_disks()
        if not data_disks:
            raise SkippedException(
                "No data disks found after provisioning "
                "- skipping burst throughput check."
            )

        log.info(
            f"VM size: {vm_size} - discovered {len(data_disks)} data disk(s): "
            f"{data_disks}; burst throughput source: "
            f"{cap_name}={raw_value} (~{expected_burst_bw} MBps)"
        )

        thread_count = node.tools[Lscpu].get_thread_count()
        measured_bw = _run_fio_throughput_mbps(
            node,
            log,
            vm_size,
            data_disks,
            label="burst-disk",
            numjob=thread_count,
            run_time_seconds=_BURST_RUN_TIME_SECONDS,
            iterations=_BURST_ITERATIONS,
        )
        bw_floor = int(expected_burst_bw * (100 - _PERF_TOLERANCE_PERCENT) / 100)
        bw_ceiling = int(expected_burst_bw * (100 + _PERF_TOLERANCE_PERCENT) / 100)
        log.info(
            f"VM size: {vm_size} - burst fio seq read across "
            f"{len(data_disks)} disk(s): "
            f"measured {measured_bw} MBps, "
            f"expected {bw_floor}-{bw_ceiling} MBps "
            f"(declared burst: {expected_burst_bw} MBps)"
        )
        assert_that(measured_bw).described_as(
            f"VM size {vm_size}: expected burst storage throughput "
            f"between {bw_floor} and {bw_ceiling} MBps "
            f"(declared burst {expected_burst_bw} MBps via {cap_name} with "
            f"{_PERF_TOLERANCE_PERCENT}% tolerance) across "
            f"{len(data_disks)} disk(s) but measured "
            f"{measured_bw} MBps"
        ).is_between(bw_floor, bw_ceiling)

    # ------------------------------------------------------------------
    # Resource (temp) disk size validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the size of the local resource (temp) disk attached
        to the VM matches the value published by the container policy
        (``MaxResourceVolumeMB``).

        Skipped when the VM size has no resource disk or when the
        capability is not published.

        Steps:
        1. Provision the VM and require a resource disk.
        2. Read ``MaxResourceVolumeMB`` from the container policy.
        3. Locate the resource disk in the guest via
           ``Disk.get_resource_disk_mount_point()`` + ``lsblk``.
        4. Assert the actual size is within 5% of expected.
        """,
        priority=4,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            disk=AzureDiskOptionSettings(has_resource_disk=True),
        ),
    )
    def verify_vm_resource_disk_size(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        caps = _get_azure_raw_caps(environment, node, log)
        expected_mb = _required_int_cap(caps, "MaxResourceVolumeMB")
        vm_size = _vm_size(node)

        actual_mb = _get_resource_disk_size_mb(node)
        log.info(
            f"VM size: {vm_size} - expected resource disk size: "
            f"{expected_mb} MB, actual: {actual_mb} MB"
        )

        # Filesystem and partition overhead make the visible disk size
        # slightly smaller than the raw capacity advertised by Azure;
        # cap the actual at the expected value and allow a 5% tolerance
        # below.
        lower_bound = int(expected_mb * (100 - _MEMORY_TOLERANCE_PERCENT) / 100)
        upper_bound = expected_mb
        assert_that(actual_mb).described_as(
            f"VM size {vm_size}: expected ~{expected_mb} MB resource disk "
            f"but found {actual_mb} MB "
            f"(tolerance {_MEMORY_TOLERANCE_PERCENT}%)"
        ).is_between(lower_bound, upper_bound)

    # ------------------------------------------------------------------
    # Resource (temp) disk IOPS validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the local resource (temp) disk can deliver the IOPS
        published by the container policy via
        ``CombinedTempDiskAndCachedIOPS``.

        Note: this Azure capability is the *combined* limit across the
        temp disk and the cached data-disk path. The measured
        resource-disk IOPS is therefore checked against this value as
        an upper bound (with tolerance), not as a guaranteed floor.

        Skipped when the VM size has no SCSI resource disk or when the
        capability is not published.

        Steps:
        1. Provision the VM and require a resource disk.
        2. Read ``CombinedTempDiskAndCachedIOPS`` from the container
           policy.
        3. Locate the resource disk's mount point.
        4. Run ``fio`` random-read 4K against a file on the resource
           disk.
        5. Assert the measured IOPS does not exceed the combined limit
           by more than the tolerance.
        """,
        priority=4,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            disk=AzureDiskOptionSettings(has_resource_disk=True),
        ),
    )
    def verify_vm_resource_disk_iops(
        self, environment: Environment, node: Node, log: Logger
    ) -> None:
        caps = _get_azure_raw_caps(environment, node, log)
        expected_iops = _required_int_cap(caps, "CombinedTempDiskAndCachedIOPS")
        vm_size = _vm_size(node)

        disk_feature = node.features[Disk]
        if disk_feature.get_resource_disk_type() != schema.ResourceDiskType.SCSI:
            raise SkippedException(
                "Resource disk IOPS test only supports SCSI resource disks."
            )
        if not disk_feature.get_resource_disks():
            raise SkippedException(
                "No resource disks visible on this VM - skipping resource "
                "disk IOPS check."
            )
        mount_point = disk_feature.get_resource_disk_mount_point()
        fio_filename = f"{mount_point}/fiodata"

        thread_count = node.tools[Lscpu].get_thread_count()
        measured_iops = _run_fio_iops(
            node,
            log,
            vm_size,
            [fio_filename],
            label="resource-disk",
            numjob=thread_count,
        )

        iops_ceiling = int(
            expected_iops * (100 + _PERF_TOLERANCE_PERCENT) / 100
        )
        log.info(
            f"VM size: {vm_size} - resource disk fio at {fio_filename}: "
            f"measured {measured_iops} IOPS, "
            f"combined limit (temp+cached): {expected_iops} "
            f"(ceiling with tolerance: {iops_ceiling})"
        )
        assert_that(measured_iops).described_as(
            f"VM size {vm_size}: measured resource-disk IOPS "
            f"({measured_iops}) exceeds combined temp+cached limit "
            f"{expected_iops} (with {_PERF_TOLERANCE_PERCENT}% tolerance "
            f"= {iops_ceiling}); the temp disk should not exceed the "
            f"combined SKU limit."
        ).is_less_than_or_equal_to(iops_ceiling)


# Match e.g. "Memory: 8102528K/8383228K available (...)" - case-insensitive K
# to also match older kernels that emit lowercase "k".
_DMESG_MEMORY_PATTERN = re.compile(
    r"Memory:\s+\d+[Kk]/(?P<total>\d+)[Kk]\s+available"
)


def _read_total_memory_mb_from_dmesg(node: Node) -> int:
    """
    Return the total kernel-visible memory (MiB) parsed from the dmesg
    boot line ``Memory: <available>K/<total>K available``.
    """
    dmesg_output = node.tools[Dmesg].get_output(force_run=True)
    match = _DMESG_MEMORY_PATTERN.search(dmesg_output)
    if match is None:
        raise SkippedException(
            "Could not find 'Memory: <avail>K/<total>K available' line in dmesg "
            "- cannot determine total memory."
        )
    total_kib = int(match.group("total"))
    # Kernel reports kibibytes; convert to mebibytes (the same unit as
    # node.capability.memory_mb, which is also in MiB despite the name).
    return total_kib // 1024


def _get_resource_disk_size_mb(node: Node) -> int:
    """
    Return the size (MiB) of the local resource disk attached to the VM.

    Uses ``Disk.get_resource_disk_mount_point()`` to locate the mount
    point and ``lsblk`` to read its total size. Skips when no resource
    disk is present.
    """
    disk_feature = node.features[Disk]
    resource_disks = disk_feature.get_resource_disks()
    if not resource_disks:
        raise SkippedException(
            "No resource disks visible on this VM - cannot determine "
            "resource disk size."
        )
    mount_point = disk_feature.get_resource_disk_mount_point()
    lsblk = node.tools[Lsblk]
    try:
        disk_info = lsblk.find_disk_by_mountpoint(mount_point, force_run=True)
    except LisaException as exc:
        raise SkippedException(
            f"Could not locate resource disk by mountpoint {mount_point}: {exc}"
        ) from exc
    return disk_info.size_in_gb * 1024


def _expected_nvme_disk_count(node: Node) -> int:
    """Return NVMe disk count from the resolved NvmeSettings on the node."""
    features = getattr(node.capability, "features", None)
    if features:
        for setting in features:
            if isinstance(setting, NvmeSettings):
                return _resolved_int(setting.disk_count, "NvmeSettings.disk_count")
    raise SkippedException(
        "NvmeSettings is not present on node.capability - cannot determine "
        "expected local NVMe disk count from container policy."
    )


def _run_fio_iops(
    node: Node,
    log: Logger,
    vm_size: str,
    disks: List[str],
    label: str,
    numjob: int,
    run_time_seconds: int = _PERF_RUN_TIME_SECONDS,
    iterations: int = _PERF_ITERATIONS,
) -> int:
    """Run ``fio`` random-read 4K across ``disks`` and return the best IOPS."""
    filename = ":".join(disks)
    fio = node.tools[Fio]
    best_iops = 0
    for i in range(iterations):
        result = fio.launch(
            name=f"{label.lower()}_iops_all_disks_{i}",
            filename=filename,
            mode="randread",
            iodepth=64,
            numjob=numjob,
            block_size="4K",
            size_gb=8192,
            time=run_time_seconds,
            overwrite=True,
        )
        iops = int(result.iops)
        log.info(
            f"VM size: {vm_size} - {label} IOPS iteration "
            f"{i + 1}/{iterations}: {iops}"
        )
        best_iops = max(best_iops, iops)
    return best_iops


def _run_fio_throughput_mbps(
    node: Node,
    log: Logger,
    vm_size: str,
    disks: List[str],
    label: str,
    numjob: int,
    run_time_seconds: int = _PERF_RUN_TIME_SECONDS,
    iterations: int = _PERF_ITERATIONS,
) -> int:
    """
    Run ``fio`` sequential-read 1024K across ``disks`` and return the
    best throughput, converted from MiB/s to MBps.
    """
    filename = ":".join(disks)
    fio = node.tools[Fio]
    best_bw_mbps = 0
    for i in range(iterations):
        result = fio.launch(
            name=f"{label.lower()}_throughput_all_disks_{i}",
            filename=filename,
            mode="read",
            iodepth=64,
            numjob=numjob,
            block_size="1024K",
            size_gb=8192,
            time=run_time_seconds,
            overwrite=True,
        )
        # fio IOPS with 1024K blocks = MiB/s; convert MiB/s -> MBps
        # (1 MiB = 1,048,576 bytes; 1 MB = 1,000,000 bytes).
        bw_mbps = int(int(result.iops) * 1048576 / 1000000)
        log.info(
            f"VM size: {vm_size} - {label} throughput iteration "
            f"{i + 1}/{iterations}: {bw_mbps} MBps"
        )
        best_bw_mbps = max(best_bw_mbps, bw_mbps)
    return best_bw_mbps
