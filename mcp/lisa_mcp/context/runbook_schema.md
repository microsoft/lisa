# LISA Runbook Schema Reference

Complete field reference for LISA runbook YAML files.

---

## Top-Level Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `"not_named"` | Run name for identification |
| `concurrency` | int | `1` | Number of parallel test environments |
| `exit_with_failed_count` | bool | `true` | Exit code reflects failure count |
| `exit_on_first_failure` | bool | `false` | Stop on first test failure |
| `test_project` | string | `""` | Project identifier for reporting |
| `test_pass` | string | `""` | Test pass identifier |
| `tags` | list[string] | null | Global tags |
| `wait_resource_timeout` | float | `5` | Minutes to wait for resource allocation |

---

## `include`

Include other runbook files. Values from included files are merged.

```yaml
include:
  - path: "./base_config.yml"
    strategy: overwrite   # "overwrite" or "add"
```

---

## `extension`

Paths to load test suites, custom platforms, notifiers, etc.

```yaml
extension:
  - "../../lisa/microsoft/testsuites"
  - "./my_custom_tests"
```

Paths are relative to the runbook file location.

---

## `platform`

List of platform configurations. At least one is required.

```yaml
platform:
  - type: azure                        # Platform type
    admin_username: "$(admin_username)" # SSH username
    admin_private_key_file: "$(admin_private_key_file)" # SSH private key path
    keep_environment: "no"             # "no", "always", "failed"
    guest_enabled: false               # Enable guest/nested VM testing

    # Azure-specific fields
    azure:
      subscription_id: "$(subscription_id)"
      deploy_location: "westus2"
      resource_group_name: ""          # Custom RG name

      marketplace:                     # Image specification
        publisher: "canonical"
        offer: "0001-com-ubuntu-server-jammy"
        sku: "22_04-lts-gen2"
        version: "latest"

      requirement:
        azure:
          vm_size: "Standard_DS2_v2"
```

### Platform Types
- `azure` — Azure Resource Manager
- `hyperv` — Hyper-V on Windows
- `libvirt` — KVM/QEMU via libvirt
- `baremetal` — Physical machines via IPMI/Redfish
- `remote` — Pre-existing machines (no provisioning)
- `local` — Local machine
- `aws` — AWS EC2
- `ready` — Pre-provisioned environment

### `keep_environment` Values
- `"no"` — Always clean up after tests (default)
- `"always"` — Never clean up (for debugging, costs money)
- `"failed"` — Keep only if a test failed (good for CI)

---

## `environment`

Pre-defined environments with specific node configurations.

```yaml
environment:
  environments:
    - name: "my-env"
      nodes:
        - type: local

    - name: "remote-env"
      nodes:
        - type: remote
          address: "10.0.0.5"
          port: 22
          username: "admin"
          password: "$(password)"

    - nodes_requirement:
        - node_count: 2
          core_count:
            min: 4
          memory_mb:
            min: 8192
```

---

## `variable`

Key-value pairs for parameterization.

```yaml
variable:
  - name: admin_username
    value: "azureuser"

  - name: admin_private_key_file
    value: ""

  - name: custom_config
    value: ""
    is_case_visible: true    # Available to test methods

  - name: vars_from_file
    file: "./variables.yml"  # Load from file
```

### Variable Substitution
Use `$(variable_name)` syntax in any string field:
```yaml
platform:
  - type: azure
    admin_username: "$(admin_username)"
```

### CLI Override
```bash
lisa -r runbook.yml -v "admin_username:myuser" -v "admin_private_key_file:~/.ssh/id_rsa"
```

---

## `testcase`

List of test selection criteria. Tests matching ANY criteria block are included.

```yaml
testcase:
  - criteria:
      area: provisioning          # Match test area
      priority: [0, 1]            # Match priority range
      tags: [smoke, basic]        # Match any tag

  - criteria:
      name: smoke_test            # Match exact test name

  - criteria:
      area: network
      priority: 2
    times: 3                      # Run matched tests 3 times
    retry: 2                      # Retry on failure
    use_new_environment: true     # Fresh env per case
    ignore_failure: false         # Count failures
```

### Criteria Fields
| Field | Type | Description |
|-------|------|-------------|
| `area` | string | TestSuiteMetadata area |
| `category` | string | TestSuiteMetadata category |
| `priority` | int or list | Priority level or range `[min, max]` |
| `tags` | list[string] | Match any tag |
| `name` | string | Test method name (exact or regex) |

---

## `notifier`

Output handlers for test results.

```yaml
notifier:
  - type: console        # Real-time terminal output
  - type: html            # HTML report
  - type: junit           # JUnit XML for CI systems
    path: "./results"
```

---

## `transformer`

Pre-execution transformers for dynamic setup.

```yaml
transformer:
  - type: to_list
    items:
      - item1
      - item2
    name: my_list
```

---

## `combinator`

Generate multiple variable combinations for parameterized runs.

```yaml
combinator:
  type: grid
  items:
    - name: vm_size
      values: ["Standard_DS2_v2", "Standard_DS3_v2"]
    - name: image
      values: ["ubuntu-22.04", "rhel-9"]
```

---

## `dev`

Development settings (usually not in production runbooks).

```yaml
dev:
  enabled: true
  mock_platform: true
  log_level: DEBUG
```
