---
applyTo: "lisa/microsoft/testsuites/**/*.py"
description: "Use when writing or editing LISA test suites and test cases. Enforces import order, decorator requirements, assertion patterns, and naming conventions."
---

# LISA Test File Conventions

## Import Order

```python
# 1. Standard library
from pathlib import Path
from typing import Any, Dict, List, Type, Union

# 2. Third-party
from assertpy import assert_that

# 3. LISA core
from lisa import (
    LisaException, Logger, Node, RemoteNode, SkippedException,
    TestCaseMetadata, TestSuite, TestSuiteMetadata,
    schema, search_space, simple_requirement,
)
from lisa.environment import Environment, EnvironmentStatus

# 4. LISA features (only those you use)
from lisa.features import Disk, NetworkInterface, SerialConsole, StartStop

# 5. LISA tools (only those you use)
from lisa.tools import Cat, Curl, Dmesg, Lspci
```

## Decorators — Always Required

```python
@TestSuiteMetadata(
    area="<area>",            # "storage", "network", "kernel", "compute"
    category="functional",    # "functional" | "performance" | "community"
    description="<purpose>",
)
class MyTests(TestSuite):

    @TestCaseMetadata(
        description="<what this validates>",
        priority=2,           # 0=critical → 5=lowest
        requirement=simple_requirement(...),
    )
    def verify_something(self, node: Node) -> None:
        ...
```

## Method Signatures — Type Hints Mandatory

```python
def verify_x(self, node: Node) -> None:                              # basic
def verify_x(self, log: Logger, node: Node) -> None:                 # with logging
def verify_x(self, log: Logger, node: RemoteNode, log_path: Path) -> None:  # reboot/panic
def verify_x(self, node: Node, environment: Environment) -> None:    # multi-node
def verify_x(self, node: Node, variables: Dict[str, Any]) -> None:   # runbook params
```

## Assertions — Use assertpy

```python
assert_that(result.exit_code).is_equal_to(0)                          # ✅
assert_that(output).described_as("NIC visible").contains("eth0")       # ✅
assert result.exit_code == 0                                           # ❌ forbidden
```

## Tool & Feature Access

```python
curl = node.tools[Curl]                    # ✅ use LISA tools
disk = node.features[Disk]                 # ✅ use LISA features
result = node.execute("curl ...")          # ❌ when Tool exists
```

## Exception Handling

- Specific exceptions only — never bare `except:` or `except Exception`
- `raise SkippedException(...)` for unmet preconditions
- `raise LisaException(...)` for test failures
- Include context in messages (iteration count, resource name)

## Node State

- `node.mark_dirty()` if: kernel params changed, drivers loaded/unloaded, network config changed, reboot required
- `after_case()` for guaranteed cleanup

## Magic Numbers — Comment Required

```python
for attempt in range(5):      # 5 retries for NIC negotiation to stabilize
timeout_seconds = 30           # max wait for kernel module load
```

## Logging — Never print()

```python
log.info(f"Validating NIC on {node.name}")        # milestones
log.debug(f"lspci output: {result.stdout[:200]}")  # details
```

## Naming

| Item | Convention | Example |
|------|-----------|---------|
| File | `lisa/microsoft/testsuites/<area>/<name>.py` | `storage/nvme.py` |
| Class | PascalCase, one per file, inherits `TestSuite` | `class NvmeTests(TestSuite)` |
| Method | `verify_` or `test_` prefix | `verify_nvme_detection` |
