# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
VM Specification Validation Test Suite

Usage
=====
See the accompanying ``lisa/microsoft/runbook/examples/vm_spec_validation.yml`` runbook
and ``lisa/microsoft/runbook/examples/vm_specs.csv`` sample for a ready-to-run example.
"""

import re
from typing import Any, Dict, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    RemoteNode,
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
from lisa.tools import Fio, Free, Kill, Lscpu, Lspci, Ntttcp
from lisa.util import constants

# ---------------------------------------------------------------------------
# Variable name constants - must match the runbook variable definitions.
# ---------------------------------------------------------------------------
VAR_VM_SIZE = "vm_size"
VAR_EXPECTED_CPU = "expected_cpu_count"
VAR_EXPECTED_MEMORY_GB = "expected_memory_gb"
VAR_EXPECTED_GPU_COUNT = "expected_gpu_count"
VAR_EXPECTED_NIC_COUNT = "expected_nic_count"
VAR_EXPECTED_MAX_DISKS = "expected_max_disks"
VAR_EXPECTED_MAX_IOPS = "expected_max_iops"
VAR_NVME_EXPECTED_MAX_DISKS = "nvme_expected_max_disks"
VAR_NVME_EXPECTED_MAX_IOPS = "nvme_expected_max_iops"
VAR_EXPECTED_NETWORK_BW = "expected_network_bw"
VAR_EXPECTED_STORAGE_THROUGHPUT = "expected_storage_throughput"

# Percentage tolerance for memory comparison.
# Azure VMs typically report slightly less memory than the nominal value
# because the hypervisor and firmware reserve a portion.
_MEMORY_TOLERANCE_PERCENT = 5

# Percentage tolerance for bandwidth / IOPS comparisons.
_PERF_TOLERANCE_PERCENT = 7

# Number of iterations for performance tests; the best result is used.
_PERF_ITERATIONS = 3


def _get_int_var(variables: Dict[str, Any], name: str) -> int:
    """Return an integer variable, raising ``SkippedException`` if missing or zero."""
    raw = variables.get(name)
    if raw is None or str(raw).strip() == "":
        raise SkippedException(f"Variable '{name}' is not set - skipping check.")
    # Strip any non-digit characters (e.g. commas, units, spaces) before parsing.
    digits_only = re.sub(r"[^\d]", "", str(raw))
    if not digits_only:
        raise SkippedException(
            f"Variable '{name}' contains no digits - skipping check."
        )
    value = int(digits_only)
    if value <= 0:
        raise SkippedException(
            f"Variable '{name}' is {value} (zero or negative) - skipping check."
        )
    return value


@TestSuiteMetadata(
    area="vm_spec_validation",
    category="functional",
    description="""
    Validates that a provisioned VM matches the hardware specification
    declared in runbook variables (CPU count, memory, NIC count, max
    disks, local NVMe disks, and optionally IOPS / bandwidth).

    Designed to be driven by runbook variables so that each iteration
    provisions and validates one VM size.
    """,
)
class VmSpecValidation(TestSuite):
    """Validate VM hardware against runbook-declared specifications."""

    # ------------------------------------------------------------------
    # CPU validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM's vCPU count matches the expected value from
        the runbook variables.

        Steps:
        1. Read expected_cpu_count from the runbook variables.
        2. Query the VM's actual vCPU count via ``lscpu``.
        3. Assert they are equal.
        """,
        priority=5,
        requirement=simple_requirement(),
    )
    def verify_vm_cpu_count(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_cpu = _get_int_var(variables, VAR_EXPECTED_CPU)
        actual_cpu = node.tools[Lscpu].get_thread_count()
        vm_size = variables.get(VAR_VM_SIZE, "unknown")
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
        of the expected value from the runbook variables.

        A tolerance of 5% is allowed because the hypervisor and
        firmware reserve a portion of RAM that is not visible to the OS.

        Steps:
        1. Read expected_memory_gb from the runbook variables.
        2. Convert expected GB to MB (*1024).
        3. Query actual total memory in KiB, convert to MiB.
        4. Assert the actual value is within 5% of expected.
        """,
        priority=5,
        requirement=simple_requirement(),
    )
    def verify_vm_memory(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_memory_gb = _get_int_var(variables, VAR_EXPECTED_MEMORY_GB)
        expected_memory_mb = expected_memory_gb * 1024
        actual_memory_mb = node.tools[Free].get_free_memory_mb()
        vm_size = variables.get(VAR_VM_SIZE, "unknown")
        log.info(
            f"VM size: {vm_size} - expected memory: {expected_memory_gb} GB "
            f"({expected_memory_mb} MB), actual memory: {actual_memory_mb} MB"
        )
        lower_bound = int(expected_memory_mb * (100 - _MEMORY_TOLERANCE_PERCENT) / 100)
        # VM sizes typically report slightly less memory than the nominal value
        # due to hypervisor/firmware reservations, so we allow the actual memory
        # to be up to the expected value but not above it.
        upper_bound = expected_memory_mb
        assert_that(actual_memory_mb).described_as(
            f"VM size {vm_size}: expected ~{expected_memory_gb} GB "
            f"({expected_memory_mb} MB) memory "
            f"but found {actual_memory_mb} MB "
            f"(tolerance {_MEMORY_TOLERANCE_PERCENT}%)"
        ).is_between(lower_bound, upper_bound)

    # ------------------------------------------------------------------
    # GPU count validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM exposes the expected number of GPU devices.

        This test is skipped when the ``expected_gpu_count`` variable
        is empty or zero.

        Steps:
        1. Read expected_gpu_count from the runbook variables.
        2. Query GPU PCI devices via ``lspci``.
        3. Assert the GPU device count matches expected_gpu_count.
        """,
        priority=5,
        requirement=simple_requirement(min_gpu_count=1),
    )
    def verify_vm_gpu_count(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_gpu_count = _get_int_var(variables, VAR_EXPECTED_GPU_COUNT)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

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
        2. Run initialize_nic_info to validate NIC/IP/VF pairing.
        3. Run sriov_basic_test to verify SR-IOV modules and VFs.
        4. Query VF devices via ``lspci``.
        5. Assert VF count matches expected_nic_count.
        """,
        priority=5,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_sriov_nic_count(
        self,
        environment: Environment,
        node: Node,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        expected_nic_count = _get_int_var(variables, VAR_EXPECTED_NIC_COUNT)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

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
        2. Skip if the VM has no synthetic NIC devices.
        3. Run initialize_nic_info to validate NIC/IP assignment.
        4. Assert total NIC count matches expected_nic_count.
        """,
        priority=5,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_synthetic_nic_count(
        self,
        environment: Environment,
        node: Node,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        expected_nic_count = _get_int_var(variables, VAR_EXPECTED_NIC_COUNT)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

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
        2. Read expected_max_disks from the runbook variables.
        3. Discover all attached raw data disks inside the guest.
        4. Assert the attached disk count matches expected_max_disks.
        """,
        priority=5,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_max_premium_ssd_disk_count(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_max_disks = _get_int_var(variables, VAR_EXPECTED_MAX_DISKS)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

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
        2. Read nvme_expected_max_disks from the runbook variables.
        3. Discover local NVMe namespaces inside the guest.
        4. Assert the NVMe disk count matches nvme_expected_max_disks.
        """,
        priority=5,
        requirement=simple_requirement(
            supported_features=[
                NvmeSettings(
                    disk_count=search_space.IntRange(min=1, choose_max_value=True)
                )
            ],
        ),
    )
    def verify_vm_nvme_disk_count(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_nvme_disks = _get_int_var(variables, VAR_NVME_EXPECTED_MAX_DISKS)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

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

        This test is skipped when the ``nvme_expected_max_iops`` variable
        is empty.

        Steps:
        1. Provision the VM with max local NVMe disks.
        2. Read nvme_expected_max_iops from the runbook variables.
        3. Discover all local NVMe namespaces.
        4. Run fio random-read 4K across all NVMe disks.
        5. Assert the aggregate IOPS >= expected (with tolerance).
        """,
        priority=5,
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
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_iops = _get_int_var(variables, VAR_NVME_EXPECTED_MAX_IOPS)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

        nvme_disks = node.features[Nvme].get_raw_nvme_disks()
        if not nvme_disks:
            raise SkippedException(
                "No local NVMe disks found - skipping NVMe IOPS check."
            )

        log.info(
            f"VM size: {vm_size} - discovered {len(nvme_disks)} NVMe disk(s): "
            f"{nvme_disks}"
        )

        # Run fio across ALL local NVMe disks simultaneously
        filename = ":".join(nvme_disks)
        fio = node.tools[Fio]
        best_iops = 0
        for i in range(_PERF_ITERATIONS):
            result = fio.launch(
                name=f"nvme_iops_all_disks_{i}",
                filename=filename,
                mode="randread",
                iodepth=64,
                numjob=4,
                block_size="4K",
                size_gb=8192,
                time=120,
                overwrite=True,
            )
            iops = int(result.iops)
            log.info(
                f"VM size: {vm_size} - NVMe IOPS iteration "
                f"{i + 1}/{_PERF_ITERATIONS}: {iops}"
            )
            best_iops = max(best_iops, iops)

        measured_iops = best_iops
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
        declared in the runbook variables by provisioning with the
        maximum number of data disks allowed by the VM size and running
        a ``fio`` random-read benchmark across all of them.

        This test is skipped when the ``expected_max_iops`` variable
        is empty.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read expected_max_iops from the runbook variables.
        3. Discover all attached raw data disks.
        4. Run fio random-read 4K across all disks simultaneously.
        5. Assert the aggregate IOPS >= expected (with tolerance).
        """,
        priority=5,
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
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_iops = _get_int_var(variables, VAR_EXPECTED_MAX_IOPS)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

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

        # Run fio across ALL data disks simultaneously using
        # colon-separated filenames.
        filename = ":".join(data_disks)
        fio = node.tools[Fio]
        cpu = node.tools[Lscpu]
        thread_count = cpu.get_thread_count()
        best_iops = 0
        for i in range(_PERF_ITERATIONS):
            result = fio.launch(
                name=f"iops_all_disks_{i}",
                filename=filename,
                mode="randread",
                iodepth=64,
                numjob=thread_count,
                block_size="4K",
                size_gb=8192,
                time=120,
                overwrite=True,
            )
            iops = int(result.iops)
            log.info(
                f"VM size: {vm_size} - disk IOPS iteration "
                f"{i + 1}/{_PERF_ITERATIONS}: {iops}"
            )
            best_iops = max(best_iops, iops)

        measured_iops = best_iops
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
        throughput declared in the runbook variables by provisioning
        with the maximum number of data disks and running a ``fio``
        sequential-read benchmark with 1024K block size across all
        of them.

        With ``block_size=1024K`` each I/O transfers 1 MiB.  The raw
        IOPS figure is converted from MiB/s to MBps
        (1 MiB/s = 1.048576 MBps) so that all comparisons use the
        same unit as the runbook specification.

        This test is skipped when the ``expected_storage_throughput``
        variable is empty or zero.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read expected_storage_throughput (MBps) from runbook variables.
        3. Discover all attached raw data disks.
        4. Run fio sequential-read 1024K across all disks.
        5. Convert measured throughput from MiB/s to MBps.
        6. Assert throughput >= expected (with tolerance).
        """,
        priority=5,
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
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_bw = _get_int_var(variables, VAR_EXPECTED_STORAGE_THROUGHPUT)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

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

        # Run fio sequential read with 1024K block size across all disks.
        # With block_size=1024K each IOP = 1 MiB; convert to MBps below.
        filename = ":".join(data_disks)
        fio = node.tools[Fio]
        cpu = node.tools[Lscpu]
        thread_count = cpu.get_thread_count()
        best_bw_mbps = 0
        for i in range(_PERF_ITERATIONS):
            result = fio.launch(
                name=f"storage_throughput_all_disks_{i}",
                filename=filename,
                mode="read",
                iodepth=64,
                numjob=thread_count,
                block_size="1024K",
                size_gb=8192,
                time=120,
                overwrite=True,
            )
            # fio IOPS with 1024K blocks = MiB/s; convert to MBps
            # 1 MiB/s = 1,048,576 / 1,000,000 MBps ((1024 * 1024) / (1000 * 1000))
            bw_mbps = int(int(result.iops) * 1048576 / 1000000)
            log.info(
                f"VM size: {vm_size} - storage throughput "
                f"iteration {i + 1}/{_PERF_ITERATIONS}: "
                f"{bw_mbps} MBps"
            )
            best_bw_mbps = max(best_bw_mbps, bw_mbps)

        measured_bw = best_bw_mbps
        bw_floor = int(
            expected_bw * (100 - _PERF_TOLERANCE_PERCENT) / 100
        )
        bw_ceiling = int(
            expected_bw * (100 + _PERF_TOLERANCE_PERCENT) / 100
        )
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
    # Network bandwidth validation — ntttcp between two nodes
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can achieve at least the expected network
        throughput declared in the runbook variables by running an
        ``ntttcp`` bandwidth test between two nodes in the same
        environment.

        This test is skipped when the ``expected_network_bw`` variable
        is empty or zero.

        Steps:
        1. Provision two nodes (sender + receiver) in the same environment.
        2. Read expected_network_bw (Mbps) from the runbook variables.
        3. Run ntttcp from the sender to the receiver.
        4. Assert measured throughput >= expected (with tolerance).
        """,
        priority=5,
        requirement=simple_requirement(
            min_count=2,
            unsupported_os=[BSD, Windows],
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def verify_vm_network_bandwidth(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        expected_bw_mbps = _get_int_var(variables, VAR_EXPECTED_NETWORK_BW)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])

        # Resolve NIC names for ntttcp.
        server_node.nics.reload()
        client_node.nics.reload()
        server_nic_name = server_node.nics.get_primary_nic().pci_device_name
        client_nic_name = client_node.nics.get_primary_nic().pci_device_name

        server_ntttcp = server_node.tools[Ntttcp]
        client_ntttcp = client_node.tools[Ntttcp]

        # Use thread count to saturate the NIC, capped at 64 to avoid
        # diminishing returns from excessive thread overhead.
        cpu = client_node.tools[Lscpu]
        thread_count = cpu.get_thread_count()
        # 64 ports max — beyond this ntttcp shows diminishing returns
        ports_count = min(thread_count, 64)

        # Start ntttcp iterations and take the best result
        best_bw_mbps = 0

        server_ntttcp.setup_system()
        client_ntttcp.setup_system()
        try:
            for i in range(_PERF_ITERATIONS):
                server_process = server_ntttcp.run_as_server_async(
                    server_nic_name,
                    run_time_seconds=60,
                    ports_count=ports_count,
                )

                try:
                    client_ntttcp.run_as_client(
                        client_nic_name,
                        server_ip=server_node.internal_address,
                        threads_count=1,
                        run_time_seconds=60,
                        ports_count=ports_count,
                    )
                finally:
                    server_node.tools[Kill].by_name(
                        server_ntttcp.command
                    )

                server_executable_result = server_process.wait_result()
                server_result = server_ntttcp.create_ntttcp_result(
                    server_executable_result
                )
                bw_mbps = int(
                    server_result.throughput_in_gbps * 1000
                )
                log.info(
                    f"VM size: {vm_size} - network bandwidth "
                    f"iteration {i + 1}/{_PERF_ITERATIONS}: "
                    f"{bw_mbps} Mbps"
                )
                best_bw_mbps = max(best_bw_mbps, bw_mbps)
        finally:
            server_node.tools[Kill].by_name(server_ntttcp.command)
            server_ntttcp.restore_system()
            client_ntttcp.restore_system()

        # ntttcp reports throughput in Gbps — convert to Mbps
        measured_bw_mbps = best_bw_mbps

        # Allow tolerance around the declared max
        bw_floor_mbps = int(
            expected_bw_mbps
            * (100 - _PERF_TOLERANCE_PERCENT)
            / 100
        )
        bw_ceiling_mbps = int(
            expected_bw_mbps
            * (100 + _PERF_TOLERANCE_PERCENT)
            / 100
        )
        log.info(
            f"VM size: {vm_size} — ntttcp network bandwidth: "
            f"measured {measured_bw_mbps} Mbps, "
            f"expected {bw_floor_mbps}-{bw_ceiling_mbps} Mbps "
            f"(declared: {expected_bw_mbps} Mbps, "
            f"tolerance: {_PERF_TOLERANCE_PERCENT}%)"
        )
        assert_that(measured_bw_mbps).described_as(
            f"VM size {vm_size}: expected network throughput "
            f"between {bw_floor_mbps} and {bw_ceiling_mbps} Mbps "
            f"(declared {expected_bw_mbps} Mbps with "
            f"{_PERF_TOLERANCE_PERCENT}% tolerance) but measured "
            f"{measured_bw_mbps} Mbps"
        ).is_between(bw_floor_mbps, bw_ceiling_mbps)
