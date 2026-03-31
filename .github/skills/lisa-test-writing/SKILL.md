---
name: lisa-test-writing
description: "LISA test authoring reference. Use when writing test suites, looking up Node/Tool/Feature APIs, or finding simple_requirement patterns. Provides API signatures, decision tables, and a starter template."
argument-hint: "Describe the test scenario you want to implement"
---

# LISA Test Writing Skill

## When to Use

- Writing a new LISA test suite or test case
- Looking up Node, Tool, or Feature API signatures
- Deciding between skip vs fail, mark_dirty vs clean
- Finding the right `simple_requirement()` pattern

## Procedure

### 1. Identify the Observable Signal

| Signal Type | Example | How to Check |
|-------------|---------|--------------|
| Command exit code | `lspci` returns 0 | `node.tools[Lspci]` |
| Kernel log entry | No panic in dmesg | `node.tools[Dmesg]` |
| File existence | `/dev/nvme0n1` present | `node.execute("test -e ...")` |
| Process state | Service running | `node.tools[Service]` |
| Platform state | VM resized | `node.features[Resize]` |
| Network state | NIC count correct | `node.features[NetworkInterface]` |

### 2. Search Before Writing

Search the workspace for existing code — never invent APIs:

- **Tools**: `lisa/tools/` — command wrappers with cross-distro compatibility
- **Features**: `lisa/features/` — platform capabilities (outside-node operations)
- **Similar tests**: `lisa/microsoft/testsuites/` — copy structure from real tests

### 3. Key Decisions

**Skip vs Fail:**

| Situation | Action |
|-----------|--------|
| Precondition unmet (wrong OS, missing HW) | `raise SkippedException("reason")` |
| Assertion failed (unexpected result) | `assert_that(...)` or `raise LisaException(...)` |

**mark_dirty:**

| Test Action | mark_dirty? |
|-------------|-------------|
| Read-only (lspci, dmesg) | No |
| Kernel parameter change | Yes |
| Driver load/unload | Yes |
| Network config change | Yes |
| Temp file created + cleaned | No |

### 4. Write Using the Template

Use the starter template at [./assets/test-template.py](./assets/test-template.py)
and the full API reference at [./references/api-reference.md](./references/api-reference.md).

## simple_requirement() Cheat Sheet

```python
simple_requirement()                                              # 1 node, 1 core
simple_requirement(supported_os=[Ubuntu, Redhat])                 # OS filter
simple_requirement(unsupported_os=[Windows, BSD])                 # OS exclusion
simple_requirement(supported_platform_type=[AZURE])               # platform filter
simple_requirement(min_core_count=4, min_memory_mb=8192)          # hardware
simple_requirement(min_gpu_count=1)                               # GPU
simple_requirement(supported_features=[SerialConsole, StartStop]) # features
simple_requirement(network_interface=Sriov())                     # SR-IOV NIC
simple_requirement(network_interface=Synthetic())                 # synthetic NIC
simple_requirement(min_count=2)                                   # multi-node
simple_requirement(environment_status=EnvironmentStatus.Deployed) # already deployed
simple_requirement(disk=schema.DiskOptionSettings(                # disk requirements
    data_disk_type=schema.DiskType.StandardHDDLRS,
    data_disk_count=search_space.IntRange(min=1),
))
```

## Common Imports

```python
from lisa import (
    LisaException, Logger, Node, RemoteNode, SkippedException,
    TestCaseMetadata, TestSuite, TestSuiteMetadata,
    schema, search_space, simple_requirement,
)
from lisa.environment import Environment, EnvironmentStatus
from lisa.features import (
    Disk, Gpu, Hibernation, NetworkInterface, Nvme,
    Resize, SecurityProfile, SerialConsole, StartStop,
)
from lisa.sut_orchestrator import AZURE
from assertpy import assert_that
```
