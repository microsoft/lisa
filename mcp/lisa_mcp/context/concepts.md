# LISA Concepts

## Runbook

A **runbook** is a YAML configuration file that drives LISA's entire test execution
pipeline. It defines what platform to use, which tests to run, how to configure
nodes, and where to report results.

### Structure

```yaml
name: my-test-run
concurrency: 2          # parallel environments

extension:              # paths to load test suites from
  - "../../lisa/microsoft/testsuites"

platform:               # one or more platform configs
  - type: azure
    admin_username: "$(admin_username)"
    admin_private_key_file: "$(admin_private_key_file)"
    keep_environment: no  # "no", "always", or "failed"

environment:            # optional pre-defined environments
  environments:
    - nodes:
        - type: remote
          address: "10.0.0.5"
          port: 22

variable:               # key-value pairs for parameterization
  - name: subscription_id
    value: ""
    is_secret: true

notifier:               # output handlers
  - type: console
  - type: html

testcase:               # test selection criteria
  - criteria:
      area: provisioning
      priority: [0, 1]
```

### Key Rules
- `platform` is a list — LISA can target multiple platforms in one run
- `testcase` is a list of filter criteria, combined with OR logic
- `extension` paths are relative to the runbook file location
- Variables from CLI (`lisa -v key:value`) override runbook values
- Runbooks can include other runbooks via `include:`

---

## Environment

An **environment** is a collection of nodes (VMs or machines) provisioned by a
platform and managed by LISA for test execution.

### Lifecycle
1. LISA reads test requirements from `@TestCaseMetadata`
2. Requirements are matched against platform capabilities via search_space
3. Platform provisions matching nodes into an environment
4. Tests execute against the environment
5. Environment is cleaned up based on `keep_environment` setting

### Key Settings
- `use_new_environment: True` — fresh environment per test case (costly)
- `keep_environment: "failed"` — preserve environment for debugging failed tests
- `environment_status: EnvironmentStatus.Deployed` — test expects a ready environment

---

## Node

A **Node** is a single machine (VM or physical) within an environment.

### Types
- `Node` — base class
- `RemoteNode` — connected via SSH (most common in cloud testing)
- `LocalNode` — the machine running LISA itself

### Key APIs
```python
# Execute a command
result = node.execute("uname -r", sudo=True)

# Use a typed tool (preferred)
info = node.tools[Uname].get_linux_information()
node.tools[Echo].run("hello")

# Access a feature
serial = node.features[SerialConsole]
serial.check_panic(saved_path=log_path)

# OS information
node.os.name          # "Ubuntu", "RHEL", etc.
node.os.information   # detailed version info

# State management
node.reboot()
node.mark_dirty()     # flag for re-provisioning

# Cross-OS path handling
path = node.get_pure_path("/etc/config")
```

---

## Feature

A **Feature** represents a platform capability that a node may or may not have.
Features abstract hardware/platform differences behind a uniform API.

### Available Features
- `StartStop` — VM lifecycle (start, stop, restart)
- `Gpu` — GPU detection and management
- `Nvme` — NVMe storage
- `NetworkInterface` — NIC configuration and management
- `SerialConsole` — serial console output access
- `Resize` — VM size changes
- `Hibernation` — VM hibernation support
- `Disk` — disk type and configuration
- `AvailabilityZone` — zone placement
- `Virtualization` — nested virtualization

### Usage Pattern
```python
# Declare requirement
@TestCaseMetadata(
    requirement=simple_requirement(supported_features=[Gpu, Nvme]),
)

# Use in test
gpu = node.features[Gpu]
nvme = node.features[Nvme]

# Check support at runtime
if node.features.is_supported(SerialConsole):
    serial = node.features[SerialConsole]
```

---

## Tool

A **Tool** wraps a Linux/Windows command as a Python class with typed methods
and structured output parsing.

### ~130 Tools Available
System: Echo, Cat, Grep, Find, Rm, Mv, Cp, Ls, Chmod, Chown
Storage: Mount, Umount, Mkfs, Lsblk, Blkid, Df, Fdisk, Parted
Network: Ip, Ethtool, Ping, Ssh, Curl, Wget, Iperf3
Kernel: GrubConfig, KernelConfig, Dmesg, Sysctl, Reboot
Diagnostics: Lspci, Lscpu, Uname, Uptime, Free, Ps, Journalctl
Package Mgmt: Apt, Dpkg, Rpm, Yum, Make
Performance: Fio, Sar, PerfTool, StressNg

### Usage
```python
# Get tool from node
echo = node.tools[Echo]
result = echo.run("hello world")

# Shorthand
node.tools.echo("hello")

# Tools handle cross-distro differences internally
node.tools[Mount].mount("/dev/sdb1", "/mnt/data")
```

---

## Platform

A **Platform** provides the infrastructure abstraction for provisioning and
managing test environments.

### Supported Platforms
- `azure` — Azure VMs via ARM templates
- `hyperv` — Hyper-V VMs
- `libvirt` — KVM/QEMU via libvirt
- `baremetal` — physical machines via IPMI/Redfish
- `remote` — pre-existing machines (SSH only, no provisioning)
- `local` — local machine
- `aws` — AWS EC2 instances

---

## Test Suite

A **TestSuite** is a Python class that groups related test cases.

### Rules
- One test class per file
- Class name in PascalCase, describes the feature area
- Inherits from `TestSuite`
- File location: `lisa/microsoft/testsuites/<area>/<name>.py`
- Decorated with `@TestSuiteMetadata(area=..., category=..., description=...)`

### Lifecycle Methods
- `before_case(log, **kwargs)` — runs before each test case
- `after_case(log, **kwargs)` — runs after each test case (guaranteed cleanup)

---

## Test Case

A **test case** is a method in a TestSuite decorated with `@TestCaseMetadata`.

### Rules
- Method name starts with `verify_` or `test_`
- Must have `priority` (0=critical, 1=high, 2=normal, 3=stress)
- Must have `description` explaining what it validates
- Must have `requirement` via `simple_requirement()`
- Parameters: `self, node: Node, log: Logger` at minimum
- Use `assert_that()` from assertpy for assertions
- Follow AAA: Arrange → Act → Assert

### Available Parameters
- `node: Node` — the test target
- `log: Logger` — test logger
- `environment: Environment` — full environment
- `log_path: Path` — path for saving artifacts
- `working_path: Path` — temp working directory
- `variables: Dict[str, Any]` — runbook variables

---

## simple_requirement()

Declares what environment capabilities a test needs.

```python
simple_requirement(
    min_count=1,                    # minimum nodes
    min_core_count=2,               # min CPU cores per node
    min_memory_mb=2048,             # min RAM
    min_nic_count=2,                # min network interfaces
    min_data_disk_count=1,          # min data disks
    min_gpu_count=1,                # min GPUs
    supported_os=[Posix],           # required OS types
    unsupported_os=[Windows],       # excluded OS types
    supported_features=[Gpu],       # required features
    unsupported_features=[],        # excluded features
    supported_platform_type=["azure"],
    environment_status=EnvironmentStatus.Deployed,
    disk=DiskPremiumSSDLRS(),       # disk type
    network_interface=Sriov(),      # NIC type
)
```

---

## Priority / Tiers

- **Priority 0 (T0)**: Critical smoke tests — basic boot, connectivity
- **Priority 1 (T1)**: High-priority functional — core features
- **Priority 2 (T2)**: Normal functional — standard validation
- **Priority 3 (T3)**: Stress, long-running, edge cases

Filter in runbook:
```yaml
testcase:
  - criteria:
      priority: [0, 1]   # run T0 and T1 only
```
