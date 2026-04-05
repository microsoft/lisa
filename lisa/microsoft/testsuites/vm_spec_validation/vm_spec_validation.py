# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
VM Specification Validation Test Suite

This test suite reads expected VM specifications from CSV-driven variables
(via the LISA CSV combinator) and validates that a provisioned VM matches
the declared hardware properties like: CPU count, memory, NIC count, max data
disks (including local NVMe), storage IOPS and network
bandwidth and GPU count where applicable.

Architecture
============

    CSV file --> CSV Combinator --> variables (is_case_visible) --> test methods
                                         |
                    +--------------------+
                    v
         +------------------------+
         | vm_size                |  Azure VM size used by the platform
         | expected_cpu_count     |  Expected vCPU count
         | expected_memory_gb     |  Expected memory in GB
         | expected_nic_count     |  Expected max NIC count
         | expected_max_disks     |  Expected max data disk count
         | expected_max_iops      |  (optional) Expected disk IOPS ceiling
         | expected_network_bw    |  (optional) Expected network bandwidth Mbps
         | expected_storage_bw    |  (optional) Expected storage bandwidth MBps
         +------------------------+

Each row in the CSV becomes one iteration of the runner (one VM size).
The platform provisions a VM with the given ``vm_size``, and the test
suite validates hardware against the expected values.

Usage
=====

See the accompanying ``vm_spec_validation.yml`` runbook and
``vm_specs.csv`` sample for a ready-to-run example.
"""

from typing import Any, Dict, List, cast

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
from lisa.tools import Fio, Free, Iperf3, Lscpu, Lspci

# ---------------------------------------------------------------------------
# Variable name constants - must match the ``column_mapping`` in the runbook.
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
VAR_EXPECTED_STORAGE_BW = "expected_storage_bw"

# Percentage tolerance for memory comparison.
# Azure VMs typically report slightly less memory than the nominal value
# because the hypervisor and firmware reserve a portion.
_MEMORY_TOLERANCE_PERCENT = 5

# Percentage tolerance for bandwidth / IOPS comparisons.
_PERF_TOLERANCE_PERCENT = 5


def _get_int_var(variables: Dict[str, Any], name: str) -> int:
    """Return an integer variable, raising ``SkippedException`` if missing or zero."""
    raw = variables.get(name)
    if raw is None or str(raw).strip() == "":
        raise SkippedException(f"Variable '{name}' is not set - skipping check.")
    value = int(raw)
    if value <= 0:
        raise SkippedException(
            f"Variable '{name}' is {value} (zero or negative) - skipping check."
        )
    return value


def _get_optional_int_var(variables: Dict[str, Any], name: str) -> int:
    """Return an integer variable, or ``-1`` if the column is empty/missing."""
    raw = variables.get(name)
    if raw is None or str(raw).strip() == "":
        return -1
    return int(raw)


def _resolve_countspace(value: Any) -> int:
    """
    Extract an integer from a LISA CountSpace capability value.

    Capabilities can be stored as plain ``int``, ``IntRange``, or a list
    thereof.  This helper normalises them to a single integer.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, search_space.IntRange):
        # For capabilities the min usually equals max (fixed value).
        return value.max if value.max else value.min
    if isinstance(value, list):
        # Return the largest value from the list of ranges.
        return max(_resolve_countspace(v) for v in value)
    return int(value)


@TestSuiteMetadata(
    area="vm_spec_validation",
    category="functional",
    description="""
    Validates that a provisioned VM matches the hardware specification
    declared in a CSV file (CPU count, memory, NIC count, max disks,
    local NVMe disks, and optionally IOPS / bandwidth).

    Designed to be run with the CSV combinator so that every row in
    the input CSV drives an independent test iteration.
    """,
)
class VmSpecValidation(TestSuite):
    """Validate VM hardware against CSV-declared specifications."""

    # Required CSV variables that must be present for any test case to run.
    _REQUIRED_CSV_VARS = [
        VAR_VM_SIZE,
        VAR_EXPECTED_CPU,
        VAR_EXPECTED_MEMORY_GB,
        VAR_EXPECTED_NIC_COUNT,
        VAR_EXPECTED_MAX_DISKS,
        VAR_EXPECTED_MAX_IOPS,
        VAR_EXPECTED_NETWORK_BW,
        VAR_EXPECTED_STORAGE_BW,
    ]

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        variables: Dict[str, Any] = kwargs.pop("variables")
        missing = [
            v
            for v in self._REQUIRED_CSV_VARS
            if variables.get(v) is None
            or str(variables.get(v)).strip() == ""
            or str(variables.get(v)).strip() == "0"
        ]
        if missing:
            raise SkippedException(
                f"Required CSV variable(s) not set or zero: {', '.join(missing)}. "
                "Ensure the CSV file and combinator column_mapping are correct."
            )

    # ------------------------------------------------------------------
    # CPU validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM's vCPU count matches the expected value from
        the CSV specification.

        Steps:
        1. Read expected_cpu_count from the CSV-provided variables.
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
        of the expected value from the CSV specification.

        A tolerance of 10%% is allowed because the hypervisor and
        firmware reserve a portion of RAM that is not visible to the OS.

        Steps:
        1. Read expected_memory_gb from the CSV-provided variables.
        2. Convert expected GB to MB (*1024).
        3. Query actual total memory in KiB, convert to MiB.
        4. Assert the actual value is within 10%% of expected.
        """,
        priority=5,
        requirement=simple_requirement(),
    )
    def verify_vm_memory(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_memory_gb = _get_int_var(variables, VAR_EXPECTED_MEMORY_GB)
        expected_memory_mb = expected_memory_gb * 1024
        # _get_field_bytes_kib returns KiB; shift right 10 to get MiB
        actual_memory_mb = node.tools[Free]._get_field_bytes_kib("Mem", "total") >> 10
        vm_size = variables.get(VAR_VM_SIZE, "unknown")
        log.info(
            f"VM size: {vm_size} - expected memory: {expected_memory_gb} GB "
            f"({expected_memory_mb} MB), actual memory: {actual_memory_mb} MB"
        )
        lower_bound = expected_memory_mb * (100 - _MEMORY_TOLERANCE_PERCENT) / 100
        assert_that(actual_memory_mb).described_as(
            f"VM size {vm_size}: expected ~{expected_memory_gb} GB "
            f"({expected_memory_mb} MB) memory "
            f"but found {actual_memory_mb} MB "
            f"(tolerance {_MEMORY_TOLERANCE_PERCENT}%)"
        ).is_greater_than_or_equal_to(int(lower_bound))

    # ------------------------------------------------------------------
    # GPU count validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM exposes the expected number of GPU devices.

        This test is skipped when the ``expected_gpu_count`` CSV column
        is empty or zero.

        Steps:
        1. Read expected_gpu_count from the CSV-provided variables.
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
        Verify the VM supports the expected number of SR-IOV NICs by
        provisioning with the maximum NIC count and validating that
        each NIC is paired with a VF device and receives an IP.

        Steps:
        1. Provision the VM with max SR-IOV NICs (choose_max_value).
        2. Run initialize_nic_info to validate NIC/IP/VF pairing.
        3. Run sriov_basic_test to verify SR-IOV modules and VFs.
        4. Assert total NIC count matches expected_nic_count from CSV.
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

        actual_nic_count = len(node.nics.nics)
        log.info(
            f"VM size: {vm_size} - expected NICs: {expected_nic_count}, "
            f"actual SR-IOV NICs: {actual_nic_count}"
        )
        assert_that(actual_nic_count).described_as(
            f"VM size {vm_size}: expected {expected_nic_count} SR-IOV NICs "
            f"but found {actual_nic_count}"
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
        4. Assert total NIC count matches expected_nic_count from CSV.
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
        2. Read expected_max_disks from the CSV-provided variables.
        3. Discover all attached raw data disks inside the guest.
        4. Assert the attached disk count matches expected_max_disks.
        """,
        priority=5,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_max_premium_data_disks(
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
        2. Read nvme_expected_max_disks from the CSV-provided variables.
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

        This test is skipped when the ``nvme_expected_max_iops`` CSV
        column is empty.

        Steps:
        1. Provision the VM with max local NVMe disks.
        2. Read nvme_expected_max_iops from the CSV-provided variables.
        3. Discover all local NVMe namespaces.
        4. Run fio random-read 4K across all NVMe disks.
        5. Assert the aggregate IOPS >= expected (with tolerance).
        """,
        priority=3,
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
        expected_iops = _get_optional_int_var(variables, VAR_NVME_EXPECTED_MAX_IOPS)
        if expected_iops <= 0:
            raise SkippedException(
                "nvme_expected_max_iops not specified in CSV "
                "- skipping NVMe IOPS check."
            )
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
        result = fio.launch(
            name="nvme_iops_all_disks",
            filename=filename,
            mode="randread",
            iodepth=64,
            numjob=4,
            block_size="4K",
            size_gb=0,
            time=30,
            overwrite=True,
        )

        measured_iops = int(result.iops)
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
        declared in the CSV specification by provisioning with the
        maximum number of data disks allowed by the VM size and running
        a ``fio`` random-read benchmark across all of them.

        This test is skipped when the ``expected_max_iops`` CSV column
        is empty.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read expected_max_iops from the CSV-provided variables.
        3. Discover all attached raw data disks.
        4. Run fio random-read 4K across all disks simultaneously.
        5. Assert the aggregate IOPS >= expected (with tolerance).
        """,
        priority=3,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_premium_disk_iops(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_iops = _get_optional_int_var(variables, VAR_EXPECTED_MAX_IOPS)
        if expected_iops <= 0:
            raise SkippedException(
                "expected_max_iops not specified in CSV - skipping IOPS check."
            )
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
        result = fio.launch(
            name="iops_all_disks",
            filename=filename,
            mode="randread",
            iodepth=64,
            numjob=thread_count,
            block_size="4K",
            size_gb=8192,
            time=120,
            overwrite=True,
        )

        measured_iops = int(result.iops)
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
    # Storage bandwidth validation — fio sequential read, 1024K blocks
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can achieve at least the expected storage
        throughput declared in the CSV specification by provisioning
        with the maximum number of data disks and running a ``fio``
        sequential-read benchmark with 1024K block size across all
        of them.

        With ``block_size=1024K`` each I/O transfers 1 MiB, so the
        reported IOPS value equals the throughput in MiB/s.

        This test is skipped when the ``expected_storage_bw`` CSV
        column is empty or zero.

        Steps:
        1. Provision the VM with max data disks (choose_max_value).
        2. Read expected_storage_bw (MBps) from the CSV variables.
        3. Discover all attached raw data disks.
        4. Run fio sequential-read 1024K across all disks.
        5. Assert throughput >= expected (with tolerance).
        """,
        priority=3,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
            ),
        ),
    )
    def verify_vm_storage_bandwidth(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_bw = _get_optional_int_var(variables, VAR_EXPECTED_STORAGE_BW)
        if expected_bw <= 0:
            raise SkippedException(
                "expected_storage_bw not specified in CSV "
                "- skipping storage bandwidth check."
            )
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

        # Discover all raw data disks attached by the platform
        data_disks = node.features[Disk].get_raw_data_disks()
        if not data_disks:
            raise SkippedException(
                "No data disks found after provisioning "
                "- skipping storage bandwidth check."
            )

        log.info(
            f"VM size: {vm_size} - discovered {len(data_disks)} data disk(s): "
            f"{data_disks}"
        )

        # Run fio sequential read with 1024K block size across all disks.
        # With block_size=1024K each IOP = 1 MiB, so IOPS == MiB/s.
        filename = ":".join(data_disks)
        fio = node.tools[Fio]
        cpu = node.tools[Lscpu]
        thread_count = cpu.get_thread_count()
        result = fio.launch(
            name="storage_bw_all_disks",
            filename=filename,
            mode="read",
            iodepth=64,
            numjob=thread_count,
            block_size="1024K",
            size_gb=8192,
            time=120,
            overwrite=True,
        )

        # With 1024K block size, IOPS == throughput in MiB/s
        measured_bw = int(result.iops)
        bw_floor = int(expected_bw * (100 - _PERF_TOLERANCE_PERCENT) / 100)
        log.info(
            f"VM size: {vm_size} - fio seq read across {len(data_disks)} disk(s): "
            f"measured {measured_bw} MiB/s, "
            f"expected >= {bw_floor} MiB/s (declared: {expected_bw} MBps)"
        )
        assert_that(measured_bw).described_as(
            f"VM size {vm_size}: expected storage throughput >= {bw_floor} MiB/s "
            f"(declared {expected_bw} MBps with "
            f"{_PERF_TOLERANCE_PERCENT}% tolerance) across "
            f"{len(data_disks)} disk(s) but measured only {measured_bw} MiB/s"
        ).is_greater_than_or_equal_to(bw_floor)

    # ------------------------------------------------------------------
    # Network bandwidth validation — iperf3 between two nodes
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can achieve at least the expected network
        throughput declared in the CSV specification by running an
        ``iperf3`` bandwidth test between two nodes in the same
        environment.

        This test is skipped when the ``expected_network_bw`` CSV
        column is empty or zero.

        Steps:
        1. Provision two nodes (client + server) in the same environment.
        2. Read expected_network_bw (Mbps) from the CSV variables.
        3. Run iperf3 from the client to the server.
        4. Assert measured throughput >= expected (with tolerance).
        """,
        priority=3,
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
        expected_bw_mbps = _get_optional_int_var(variables, VAR_EXPECTED_NETWORK_BW)
        if expected_bw_mbps <= 0:
            raise SkippedException(
                "expected_network_bw not specified in CSV "
                "— skipping network bandwidth check."
            )
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])

        # Start iperf3 server in the background
        iperf3_server = server_node.tools[Iperf3]
        iperf3_server.run_as_server_async()

        try:
            iperf3_client = client_node.tools[Iperf3]

            # Use multiple parallel streams to saturate the link.
            # Cap at 64 to avoid diminishing returns from thread overhead.
            cpu = client_node.tools[Lscpu]
            thread_count = cpu.get_thread_count()
            parallel_streams = min(thread_count, 64)

            result = iperf3_client.run_as_client_async(
                server_ip=server_node.internal_address,
                parallel_number=parallel_streams,
                run_time_seconds=30,  # 30s for stable throughput measurement
            )
            measured_bw_mbps = result.wait_result()
        finally:
            # Ensure the iperf3 server process is cleaned up
            iperf3_server.kill()

        # Allow tolerance below the declared max
        bw_floor_mbps = int(
            expected_bw_mbps * (100 - _PERF_TOLERANCE_PERCENT) / 100
        )
        log.info(
            f"VM size: {vm_size} - iperf3 network bandwidth: "
            f"measured {measured_bw_mbps} Mbps, "
            f"expected >= {bw_floor_mbps} Mbps "
            f"(declared: {expected_bw_mbps} Mbps)"
        )
        assert_that(measured_bw_mbps).described_as(
            f"VM size {vm_size}: expected network throughput "
            f">= {bw_floor_mbps} Mbps (declared {expected_bw_mbps} Mbps "
            f"with {_PERF_TOLERANCE_PERCENT}% tolerance) but measured "
            f"only {measured_bw_mbps} Mbps"
        ).is_greater_than_or_equal_to(bw_floor_mbps)

    # ------------------------------------------------------------------
    # End-to-end hardware summary (informational, always runs)
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Collect and log a full hardware summary of the provisioned VM
        and compare it against all CSV-declared specifications in a
        single pass.  This test case provides a convenient overview
        without failing on individual mismatches - each property
        mismatch is collected and reported together at the end.

        Steps:
        1. Read all expected_* variables from the CSV.
        2. Query actual CPU, memory, NIC count, max disk count.
        3. Collect mismatches and assert that none exist.
        """,
        priority=2,
        requirement=simple_requirement(),
    )
    def verify_vm_spec_summary(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        vm_size = variables.get(VAR_VM_SIZE, "unknown")
        mismatches: List[str] = []

        # --- CPU ---
        expected_cpu = _get_optional_int_var(variables, VAR_EXPECTED_CPU)
        if expected_cpu > 0:
            actual_cpu = node.tools[Lscpu].get_thread_count()
            log.info(f"  CPU: expected={expected_cpu}, actual={actual_cpu}")
            if actual_cpu != expected_cpu:
                mismatches.append(f"CPU: expected {expected_cpu}, got {actual_cpu}")

        # --- Memory ---
        expected_mem_gb = _get_optional_int_var(variables, VAR_EXPECTED_MEMORY_GB)
        if expected_mem_gb > 0:
            expected_mem_mb = expected_mem_gb * 1024
            actual_mem_mb = node.tools[Free]._get_field_bytes_kib("Mem", "total") >> 10
            lower_bound = int(expected_mem_mb * (100 - _MEMORY_TOLERANCE_PERCENT) / 100)
            log.info(
                f"  Memory: expected>={lower_bound} MB "
                f"({expected_mem_gb} GB), actual={actual_mem_mb} MB"
            )
            if actual_mem_mb < lower_bound:
                mismatches.append(
                    f"Memory: expected >= {lower_bound} MB "
                    f"({expected_mem_gb} GB), got {actual_mem_mb} MB"
                )

        # --- NIC count (guest-visible NICs with IPs) ---
        expected_nic = _get_optional_int_var(variables, VAR_EXPECTED_NIC_COUNT)
        if expected_nic > 0:
            node.nics.reload()
            nics_with_ip = [
                name for name, info in node.nics.nics.items() if info.ip_addr
            ]
            actual_nic = len(nics_with_ip)
            log.info(f"  NICs with IP: expected>={expected_nic}, actual={actual_nic}")
            if actual_nic < expected_nic:
                mismatches.append(
                    f"NICs with IP: expected >= {expected_nic}, got {actual_nic}"
                )

        # --- Max data disks ---
        expected_disks = _get_optional_int_var(variables, VAR_EXPECTED_MAX_DISKS)
        if expected_disks > 0:
            disk_cap = node.capability.disk
            if disk_cap and hasattr(disk_cap, "max_data_disk_count"):
                actual_disks = _resolve_countspace(disk_cap.max_data_disk_count)
                log.info(
                    f"  Max disks: expected>={expected_disks}, "
                    f"actual={actual_disks}"
                )
                if actual_disks < expected_disks:
                    mismatches.append(
                        f"Max disks: expected >= {expected_disks}, "
                        f"got {actual_disks}"
                    )

        log.info(
            f"VM size: {vm_size} - summary complete, "
            f"{len(mismatches)} mismatch(es) found."
        )

        assert_that(mismatches).described_as(
            f"VM size {vm_size}: spec mismatches detected:\n"
            + "\n".join(f"  - {m}" for m in mismatches)
        ).is_empty()
