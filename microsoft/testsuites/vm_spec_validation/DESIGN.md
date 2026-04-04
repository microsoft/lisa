# VM Specification Validation — Design Document

## Overview

This module validates that Azure VMs match their declared hardware specifications.
A CSV file defines the expected properties for each VM size (CPU count, memory, NIC count, max disks, IOPS, etc.), and the LISA CSV combinator iterates over each row, provisioning a VM and running validation tests against it.

## Architecture

```
vm_specs.csv  ──►  CSV Combinator  ──►  variables (is_case_visible)  ──►  Test Suite
  (N rows)         (built-in LISA)       (vm_size, expected_cpu, ...)       (6 test cases)
      │                                                                         │
      └── Each row = one runner iteration = one VM provisioned & validated ─────┘
```

### Data Flow

1. The **runbook** (`vm_spec_validation.yml`) includes the Azure platform config and declares a `combinator: type: csv` pointing at the CSV file.
2. The **CSV combinator** reads each row and maps columns to LISA variables via `column_mapping`.
3. Variables are marked `is_case_visible: true` in the runbook so they reach test methods.
4. The **runner** calls `combinator.fetch()` in a loop — each row produces a new iteration with its own set of variables (including `vm_size`, which the Azure platform uses to provision).
5. **Test methods** receive `variables: Dict[str, Any]` and use LISA tools (`Lscpu`, `Free`, `Lsblk`, `Fio`) and platform capabilities (`node.capability`) to validate actual hardware against expected values.

### CSV Variables

| CSV Column           | LISA Variable          | Description                              | Required |
|----------------------|------------------------|------------------------------------------|----------|
| `vm_size`            | `vm_size`              | Azure VM size (e.g. `Standard_D4s_v3`)   | Yes      |
| `expected_cpu_count` | `expected_cpu_count`   | Expected vCPU count                      | Yes      |
| `expected_memory_mb` | `expected_memory_mb`   | Expected memory in MB                    | Yes      |
| `expected_nic_count` | `expected_nic_count`   | Expected max NIC count                   | Yes      |
| `expected_max_disks` | `expected_max_disks`   | Expected max data disk count             | Yes      |
| `expected_max_iops`  | `expected_max_iops`    | Expected disk IOPS ceiling               | Optional |
| `expected_network_bw`| `expected_network_bw`  | Expected network bandwidth (Mbps)        | Optional |
| `expected_storage_bw`| `expected_storage_bw`  | Expected storage bandwidth (MBps)        | Optional |

Optional columns can be left empty; the corresponding tests are skipped gracefully.

## Files

| File | Purpose |
|------|---------|
| `vm_spec_validation.py` | Test suite — 6 test cases validating CPU, memory, NICs, disks, IOPS, and a combined summary |
| `vm_specs.csv`           | Sample CSV with 12 common Azure VM sizes |
| `vm_spec_validation.yml` | Runbook wiring the CSV combinator to the test suite and Azure platform |
| `__init__.py`            | Python package marker |
| `DESIGN.md`             | This document |

## Test Cases

| Method                     | Priority | Validates                                                                 |
|----------------------------|----------|---------------------------------------------------------------------------|
| `verify_vm_cpu_count`      | P1       | vCPU count == `expected_cpu_count`                                        |
| `verify_vm_memory`         | P1       | Total memory within 10% of `expected_memory_mb`                           |
| `verify_vm_nic_count`      | P1       | Max NIC count >= `expected_nic_count` (platform capability or guest enum) |
| `verify_vm_max_data_disks` | P1       | Max data disks >= `expected_max_disks` (platform capability)              |
| `verify_vm_disk_iops`      | P3       | Fio random-read 4K IOPS >= `expected_max_iops` (20% tolerance)           |
| `verify_vm_spec_summary`   | P2       | All-in-one: collects all mismatches and reports them together             |

### Tolerance Values

- **Memory**: 10% — Azure VMs report less than nominal due to hypervisor/firmware reservation.
- **IOPS**: 20% — real-world I/O varies with host load, caching state, and warm-up time.

## How to Run

```bash
lisa -r microsoft/testsuites/vm_spec_validation/vm_spec_validation.yml \
     --variable "subscription_id:<YOUR_SUBSCRIPTION_ID>" \
     --variable "csv_file:microsoft/testsuites/vm_spec_validation/vm_specs.csv" \
     --variable "location:westus3" \
     --variable "marketplace_image:canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"
```

### Customisation

- **Different VM sizes**: Edit `vm_specs.csv` or point `csv_file` to a different file.
- **Different image**: Override `marketplace_image` on the CLI.
- **Subset of tests**: Add priority or name filters to the `testcase:` section in the runbook.
- **Additional validations**: Add new test methods to `VmSpecValidation` and corresponding columns to the CSV.

## Design Decisions

1. **Reuse existing CSV combinator** — LISA already has `lisa/combinators/csv_combinator.py`. No new combinator code is needed.
2. **Platform capabilities for NIC/disk limits** — Using `node.capability.network_interface.max_nic_count` and `node.capability.disk.max_data_disk_count` is more reliable than enumerating devices inside the guest (which only shows currently attached, not maximum supported).
3. **Guest-side tools for CPU/memory** — `Lscpu` and `Free` measure what the OS actually sees, which is the ground truth for these properties.
4. **Optional performance columns** — IOPS/bandwidth benchmarks are expensive and not always needed, so they skip cleanly when the CSV column is empty.
5. **Summary test case** — `verify_vm_spec_summary` runs all checks in a single pass so the user gets one consolidated failure message instead of multiple separate failures.
6. **`_resolve_countspace` helper** — LISA stores capabilities as `CountSpace` (int, IntRange, or list). This helper safely extracts a plain integer for comparison.

## Extending

### Adding Network Bandwidth Validation

To validate network bandwidth (`expected_network_bw`), add a test method that:

1. Requires `min_count=2` (client + server nodes).
2. Reads `expected_network_bw` from variables.
3. Runs `Iperf3` between the two nodes.
4. Asserts measured throughput >= expected with tolerance.

### Adding Storage Throughput Validation

Similar to IOPS, but run `fio` in sequential-read mode with large block sizes (e.g. 1M) and compare throughput in MBps against `expected_storage_bw`.
