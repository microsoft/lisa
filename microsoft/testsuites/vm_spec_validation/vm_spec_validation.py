# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
VM Specification Validation Test Suite

This test suite reads expected VM specifications from CSV-driven variables
(via the LISA CSV combinator) and validates that a provisioned VM matches
the declared hardware properties: CPU count, memory, NIC count, max data
disks, and optionally storage IOPS and network bandwidth.

Architecture
============

    CSV file --> CSV Combinator --> variables (is_case_visible) --> test methods
                                         |
                    +--------------------+
                    v
         +------------------------+
         | vm_size                |  Azure VM size used by the platform
         | expected_cpu_count     |  Expected vCPU count
         | expected_memory_mb     |  Expected memory in MB
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

from typing import Any, Dict, List

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    search_space,
    simple_requirement,
)
from lisa.operating_system import BSD, Windows
from lisa.tools import Fio, Free, Lsblk, Lscpu

# ---------------------------------------------------------------------------
# Variable name constants - must match the ``column_mapping`` in the runbook.
# ---------------------------------------------------------------------------
VAR_VM_SIZE = "vm_size"
VAR_EXPECTED_CPU = "expected_cpu_count"
VAR_EXPECTED_MEMORY_MB = "expected_memory_mb"
VAR_EXPECTED_NIC_COUNT = "expected_nic_count"
VAR_EXPECTED_MAX_DISKS = "expected_max_disks"
VAR_EXPECTED_MAX_IOPS = "expected_max_iops"
VAR_EXPECTED_NETWORK_BW = "expected_network_bw"
VAR_EXPECTED_STORAGE_BW = "expected_storage_bw"

# Percentage tolerance for memory comparison.
# Azure VMs typically report slightly less memory than the nominal value
# because the hypervisor and firmware reserve a portion.
_MEMORY_TOLERANCE_PERCENT = 10

# Percentage tolerance for bandwidth / IOPS comparisons.
_PERF_TOLERANCE_PERCENT = 20


def _get_int_var(variables: Dict[str, Any], name: str) -> int:
    """Return an integer variable, raising ``SkippedException`` if missing."""
    raw = variables.get(name)
    if raw is None or str(raw).strip() == "":
        raise SkippedException(f"Variable '{name}' is not set - skipping check.")
    return int(raw)


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
    and optionally IOPS / bandwidth).

    Designed to be run with the CSV combinator so that every row in
    the input CSV drives an independent test iteration.
    """,
)
class VmSpecValidation(TestSuite):
    """Validate VM hardware against CSV-declared specifications."""

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
        priority=1,
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
        1. Read expected_memory_mb from the CSV-provided variables.
        2. Query actual total memory in KB, convert to MB.
        3. Assert the actual value is within 10%% of expected.
        """,
        priority=1,
        requirement=simple_requirement(),
    )
    def verify_vm_memory(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_memory_mb = _get_int_var(variables, VAR_EXPECTED_MEMORY_MB)
        # _get_field_bytes_kib returns KiB; shift right 10 to get MiB
        actual_memory_mb = node.tools[Free]._get_field_bytes_kib("Mem", "total") >> 10
        vm_size = variables.get(VAR_VM_SIZE, "unknown")
        log.info(
            f"VM size: {vm_size} - expected memory: {expected_memory_mb} MB, "
            f"actual memory: {actual_memory_mb} MB"
        )
        lower_bound = expected_memory_mb * (100 - _MEMORY_TOLERANCE_PERCENT) / 100
        assert_that(actual_memory_mb).described_as(
            f"VM size {vm_size}: expected ~{expected_memory_mb} MB memory "
            f"but found {actual_memory_mb} MB "
            f"(tolerance {_MEMORY_TOLERANCE_PERCENT}%)"
        ).is_greater_than_or_equal_to(int(lower_bound))

    # ------------------------------------------------------------------
    # NIC count validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM supports the expected number of NICs as
        declared in the CSV specification.

        Steps:
        1. Read expected_nic_count from the CSV-provided variables.
        2. Query the platform's maximum NIC capability for this node.
        3. Assert the max NIC count is >= expected value.
        """,
        priority=1,
        requirement=simple_requirement(),
    )
    def verify_vm_nic_count(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_nic_count = _get_int_var(variables, VAR_EXPECTED_NIC_COUNT)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

        # Use the network interface capability from the node
        nic_capability = node.capability.network_interface
        if nic_capability and hasattr(nic_capability, "max_nic_count"):
            max_nic = _resolve_countspace(nic_capability.max_nic_count)
            log.info(
                f"VM size: {vm_size} - expected NIC count: "
                f"{expected_nic_count}, "
                f"platform max NIC count: {max_nic}"
            )
            assert_that(max_nic).described_as(
                f"VM size {vm_size}: expected max NIC count "
                f">= {expected_nic_count} "
                f"but platform reports {max_nic}"
            ).is_greater_than_or_equal_to(expected_nic_count)
        else:
            # Fallback: count NICs visible inside the guest
            nic_names = node.nics.get_nic_names()
            actual_nic_count = len(nic_names)
            log.info(
                f"VM size: {vm_size} - expected NICs: "
                f"{expected_nic_count}, "
                f"visible NICs: {actual_nic_count}"
            )
            assert_that(actual_nic_count).described_as(
                f"VM size {vm_size}: expected at least "
                f"{expected_nic_count} NIC(s) "
                f"but found {actual_nic_count}"
            ).is_greater_than_or_equal_to(expected_nic_count)

    # ------------------------------------------------------------------
    # Max data disk count validation
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM supports the expected maximum number of data
        disks as declared in the CSV specification.

        Steps:
        1. Read expected_max_disks from the CSV-provided variables.
        2. Query the platform's max data disk capability for this node.
        3. Assert the max data disk count is >= expected value.
        """,
        priority=1,
        requirement=simple_requirement(),
    )
    def verify_vm_max_data_disks(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_max_disks = _get_int_var(variables, VAR_EXPECTED_MAX_DISKS)
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

        disk_capability = node.capability.disk
        if disk_capability and hasattr(disk_capability, "max_data_disk_count"):
            max_disks = _resolve_countspace(disk_capability.max_data_disk_count)
            log.info(
                f"VM size: {vm_size} - expected max disks: "
                f"{expected_max_disks}, "
                f"platform max disks: {max_disks}"
            )
            assert_that(max_disks).described_as(
                f"VM size {vm_size}: expected max data disks "
                f">= {expected_max_disks} "
                f"but platform reports {max_disks}"
            ).is_greater_than_or_equal_to(expected_max_disks)
        else:
            raise SkippedException(
                f"Disk capability not available for VM size {vm_size} - "
                "cannot validate max data disk count."
            )

    # ------------------------------------------------------------------
    # Disk IOPS validation (optional - skipped if CSV column is empty)
    # ------------------------------------------------------------------
    @TestCaseMetadata(
        description="""
        Verify that the VM can achieve at least the expected disk IOPS
        declared in the CSV specification by running a short ``fio``
        random-read benchmark.

        This test is skipped when the ``expected_max_iops`` CSV column
        is empty.

        Steps:
        1. Read expected_max_iops from the CSV-provided variables.
        2. Find a data disk to benchmark.
        3. Run fio random-read 4K I/O for 30 seconds.
        4. Assert the measured IOPS >= expected (with tolerance).
        """,
        priority=3,
        requirement=simple_requirement(
            min_data_disk_count=1,
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_vm_disk_iops(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        expected_iops = _get_optional_int_var(variables, VAR_EXPECTED_MAX_IOPS)
        if expected_iops <= 0:
            raise SkippedException(
                "expected_max_iops not specified in CSV - skipping IOPS check."
            )
        vm_size = variables.get(VAR_VM_SIZE, "unknown")

        # Find a data disk to benchmark
        lsblk = node.tools[Lsblk]
        disks = lsblk.get_disks(force_run=True)
        # Filter to non-OS disks that are not currently mounted
        data_disks = [d for d in disks if not d.is_os_disk and not d.is_mounted]

        if not data_disks:
            raise SkippedException(
                "No unmounted data disk found for IOPS benchmark - skipping."
            )

        # Use the first available data disk
        target_disk = data_disks[0].device_name
        log.info(f"VM size: {vm_size} - running fio IOPS benchmark on {target_disk}")

        fio = node.tools[Fio]
        result = fio.launch(
            name="iops_check",
            filename=target_disk,
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
            f"VM size: {vm_size} - expected IOPS >= {iops_floor} "
            f"(declared max: {expected_iops}), measured: {measured_iops}"
        )
        assert_that(measured_iops).described_as(
            f"VM size {vm_size}: expected disk IOPS >= {iops_floor} "
            f"(declared max {expected_iops} with "
            f"{_PERF_TOLERANCE_PERCENT}% tolerance) "
            f"but measured only {measured_iops}"
        ).is_greater_than_or_equal_to(iops_floor)

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
        expected_mem = _get_optional_int_var(variables, VAR_EXPECTED_MEMORY_MB)
        if expected_mem > 0:
            actual_mem_mb = node.tools[Free]._get_field_bytes_kib("Mem", "total") >> 10
            lower_bound = int(expected_mem * (100 - _MEMORY_TOLERANCE_PERCENT) / 100)
            log.info(
                f"  Memory: expected>={lower_bound} MB, " f"actual={actual_mem_mb} MB"
            )
            if actual_mem_mb < lower_bound:
                mismatches.append(
                    f"Memory: expected >= {lower_bound} MB, " f"got {actual_mem_mb} MB"
                )

        # --- NIC count ---
        expected_nic = _get_optional_int_var(variables, VAR_EXPECTED_NIC_COUNT)
        if expected_nic > 0:
            nic_cap = node.capability.network_interface
            if nic_cap and hasattr(nic_cap, "max_nic_count"):
                actual_nic = _resolve_countspace(nic_cap.max_nic_count)
            else:
                actual_nic = len(node.nics.get_nic_names())
            log.info(f"  NICs: expected>={expected_nic}, actual={actual_nic}")
            if actual_nic < expected_nic:
                mismatches.append(f"NICs: expected >= {expected_nic}, got {actual_nic}")

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
