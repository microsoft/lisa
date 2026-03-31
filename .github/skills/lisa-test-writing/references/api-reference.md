# LISA Test Writing — API Reference

## Node (`lisa/node.py`)

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `node.tools` | `Tools` | Tool instances: `node.tools[Curl]` |
| `node.features` | `Features` | Feature instances: `node.features[Disk]` |
| `node.log` | `Logger` | Node-scoped logger |
| `node.name` | `str` | Display name |
| `node.os` | `OperatingSystem` | OS detection (`node.os.is_posix`) |
| `node.is_dirty` | `bool` | Whether node state was modified |
| `node.working_path` | `PurePath` | Remote working directory |
| `node.nics` | `Nics` | Network interface details |

### execute()

```python
result = node.execute(
    cmd="ls /dev/nvme*",
    shell=False,                          # shell interpretation
    sudo=False,                           # run with sudo
    timeout=None,                         # seconds
    expected_exit_code=0,                 # int or Iterable[int]
    expected_exit_code_failure_message="", # custom error
    cwd=None,                             # working directory
)
result.stdout       # str
result.stderr       # str
result.exit_code    # int
result.assert_exit_code(0, "should succeed")  # shorthand assertion
```

### Other Methods

```python
node.mark_dirty()                    # won't be reused by next test
node.test_connection()               # returns bool
node.check_kernel_error()            # raises if panic/errors found
node.expand_env_path("$HOME/.cfg")   # expand env variables
node.get_pure_path("/some/path")     # cross-OS path
```

## Tool Pattern (`lisa/tools/`)

All tools inherit from `Tool` base class:

```python
class Tool:
    command: str              # binary name
    can_install: bool         # supports auto-install?
    def run(self, parameters="", ...) -> ExecutableResult: ...
    def get_version(self) -> VersionInfo: ...
```

### Common Tools

| Tool | Command | Key Methods |
|------|---------|-------------|
| `Cat` | `cat` | `read(path)` |
| `Curl` | `curl` | `fetch(url)` |
| `Dmesg` | `dmesg` | `check_kernel_errors()` |
| `Fdisk` | `fdisk` | `make_partition()`, `delete_partitions()` |
| `Fio` | `fio` | performance benchmarks |
| `Ip` | `ip` | `get_info()`, `addr_show()` |
| `Iperf3` | `iperf3` | network performance |
| `Lscpu` | `lscpu` | `get_core_count()`, `get_architecture()` |
| `Lspci` | `lspci` | `get_devices()`, `get_device_names_by_type()` |
| `Mdadm` | `mdadm` | `create_raid()` |
| `Mkfs` | `mkfs` | `format_disk()` |
| `Mount` | `mount` | `mount()`, `umount()` |
| `Service` | `systemctl` | `restart()`, `is_active()` |
| `Sysctl` | `sysctl` | `get()`, `set()` |

## Feature Pattern (`lisa/features/`)

All features inherit from `Feature` base class:

```python
class Feature:
    def enabled(self) -> bool: ...
    @classmethod
    def settings_type(cls) -> Type[FeatureSettings]: ...
```

### Available Features

| Feature | Purpose | Key Methods |
|---------|---------|-------------|
| `Disk` | Disk management | `get_raw_data_disks()` |
| `Gpu` | GPU detection | GPU validation |
| `Hibernation` | VM hibernate | hibernation support check |
| `NetworkInterface` | NIC ops | `switch_sriov()`, `attach_nics()`, `get_nic_count()` |
| `Nvme` | NVMe storage | NVMe device handling |
| `Resize` | VM resizing | resize operations |
| `SecurityProfile` | Security | secure boot, TVM |
| `SerialConsole` | Serial log | `get_console_log()`, `check_panic()` |
| `StartStop` | VM lifecycle | start/stop/restart |

### Configuration Shorthands

```python
from lisa.features import Sriov, Synthetic
simple_requirement(network_interface=Sriov())        # SR-IOV NIC
simple_requirement(network_interface=Synthetic())     # synthetic NIC

from lisa.features import DiskPremiumSSDLRS, DiskStandardSSDLRS
simple_requirement(disk=DiskPremiumSSDLRS())          # premium SSD
```

## Metadata

### @TestSuiteMetadata

```python
@TestSuiteMetadata(
    area="storage",          # functional area
    category="functional",   # "functional" | "performance" | "community"
    description="...",       # suite purpose
    owner="Microsoft",       # optional
    tags=["tag1"],           # optional
)
```

### @TestCaseMetadata

```python
@TestCaseMetadata(
    description="...",               # what the test validates
    priority=2,                      # 0=critical → 5=lowest
    timeout=3600,                    # seconds (default 3600)
    use_new_environment=False,       # request fresh environment
    requirement=simple_requirement(...),
)
```

## Exception Types

| Exception | When | Effect |
|-----------|------|--------|
| `SkippedException` | Precondition not met | test skipped |
| `LisaException` | Test logic failure | test fails |
| `TcpConnectionException` | SSH/connection issue | connection retry |
| `PassedException` | Test passed early | test passes |

## Utility Functions

```python
from lisa.util import check_till_timeout, retry_without_exceptions, find_patterns_in_lines
from lisa import create_timer

# Poll until condition true or timeout
check_till_timeout(
    lambda: node.tools[Service].is_active("walinuxagent"),
    timeout_message="agent not active",
    timeout=60,
)
```
