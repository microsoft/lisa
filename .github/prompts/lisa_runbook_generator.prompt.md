# LISA Runbook YAML Generator

You generate LISA runbook YAML files for running tests. Ask the user what scenario they need, then produce a complete, valid runbook.

---

## Step 1: Clarify the Scenario

Before generating YAML, ask:
1. **What tests?** (specific test name, area, smoke, tier — or passed via CLI variable)
2. **What platform?** (azure, ready, qemu, openvmm)
3. **What images?** (see Image Formats below)
4. **Special requirements?** (security profile, WSL, purchase plan, disk/NIC)
5. **Azure auth method?** (only when platform is azure — see Auth Methods below)

### Image Formats

LISA supports 4 image types under `platform.requirement.azure`:

**Marketplace (string shorthand)** — most common, `"publisher offer sku version"`:
```yaml
marketplace: "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"
```

Common marketplace images:
| Distro | String |
|--------|--------|
| Ubuntu 22.04 Gen2 | `canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest` |
| Ubuntu 24.04 | `canonical ubuntu-24_04-lts server latest` |
| RHEL 9.5 Gen2 | `redhat rhel 95_gen2 latest` |
| Azure Linux 3 | `microsoftcblmariner azure-linux-3 azure-linux-3 latest` |
| Debian 12 Gen2 | `debian debian-12 12-gen2 latest` |
| SLES 15 SP6 Gen2 | `suse sles-15-sp6 gen2 latest` |
| Windows Server 2022 Gen2 | `MicrosoftWindowsServer WindowsServer 2022-datacenter-g2 latest` |

To specify a security profile, use the object format (see below).

**Marketplace (object)** — required for `security_profile` or `purchase_plan`:
```yaml
marketplace:
  publisher: "canonical"
  offer: "0001-com-ubuntu-server-jammy"
  sku: "22_04-lts-gen2"
  version: "latest"
  security_profile: ["secureboot"]
```

**VHD** — custom OS disk from a storage blob URL. Always specify `hyperv_generation` (1 or 2) and `architecture` (`x64` or `Arm64`) — LISA cannot infer these from a raw VHD:
```yaml
vhd:
  vhd_path: "https://mystorageaccount.blob.core.windows.net/vhds/my-image.vhd"
  hyperv_generation: 2      # 1 or 2; required for correct VM generation selection
  architecture: x64         # x64 or Arm64
```

> **ARM64 VHD limitation:** Azure does not support deploying an ARM64 VM directly from a raw VHD blob. When the VHD is ARM64, use one of two approaches:
>
> **Option A — Use a Shared Image Gallery (SIG) directly** (if the VHD has already been imported into a gallery):
> ```yaml
> shared_gallery:
>   subscription_id: "$(subscription_id)"
>   resource_group_name: "my-rg"
>   image_gallery: "myGallery"
>   image_definition: "myArm64ImageDef"   # definition must have architecture=Arm64
>   image_version: "latest"
> ```
>
> **Option B — Use the `azure_sig` transformer** to import the VHD into a SIG before the test runs. The transformer creates the gallery, image definition (with `gallery_image_architecture: Arm64`), and image version, then exposes the SIG URL via a renamed variable:
> ```yaml
> transformer:
>   - type: azure_sig
>     vhd: "https://mystorageaccount.blob.core.windows.net/vhds/my-arm64.vhd"
>     gallery_resource_group_name: "my-rg"
>     gallery_name: "myGallery"
>     gallery_image_location:
>       - westus3
>     gallery_image_hyperv_generation: 2
>     gallery_image_architecture: Arm64
>     gallery_image_name: "my-arm64-image"
>     gallery_image_fullname: "Microsoft Linux Arm64 1.0.0"
>     rename:
>       azure_sig_url: shared_gallery   # injects result as $(shared_gallery)
> ```
> Then reference `$(shared_gallery)` in the platform `shared_gallery` field.

**Shared Image Gallery (SIG)** — image from Azure Compute Gallery:
```yaml
shared_gallery:
  subscription_id: "$(subscription_id)"
  resource_group_name: "my-rg"
  image_gallery: "myGallery"
  image_definition: "myImageDef"
  image_version: "latest"
```

**Community Gallery** — public community gallery image:
```yaml
community_gallery_image:
  image_gallery: "myPublicGallery-xxxx"
  image_definition: "myImageDef"
  image_version: "latest"
  location: "westus3"
```

---

## Step 2: YAML Structure Reference

Top-level sections (only `platform` + `testcase` are required):

| Section | Purpose |
|---------|---------|
| `name` | Descriptive run name |
| `include` | Inherit from other YAML files: `- path: ./azure.yml` |
| `extension` | Extra test module paths: `- "<lisa_repo_path>/lisa/microsoft/testsuites"` |
| `variable` | Parameters with `$(name)` substitution. Supports `is_secret: true`, `is_case_visible: true`, `file: ./secrets.yml` |
| `platform` | Where to run (azure, ready, qemu, openvmm) |
| `testcase` | What to run — filter by priority, name, area |
| `environment` | Node definitions (optional — platform auto-provisions) |
| `concurrency` | Parallel environment count |
| `transformer` | Pre-test operations |
| `combinator` | Matrix expansion (grid, batch) |
| `notifier` | Output: `console`, `html`, `junit` |

Variable resolution order: CLI args > runbook > included files > defaults.

---

## Step 3: Platform Configuration

**Azure:**
```yaml
platform:
  - type: azure
    admin_username: $(admin_username)
    # Prefer admin_private_key_file over admin_password.
    # If both are omitted, LISA generates an SSH key pair at runtime — this is the recommended default.
    admin_private_key_file: $(admin_private_key_file)  # path to existing private key, or omit entirely
    azure:
      subscription_id: $(subscription_id)
      credential:            # see Auth Methods below; omit to use DefaultAzureCredential
        type: azcli
    requirement:
      azure:
        marketplace: $(marketplace_image)
        location: $(location)
        vm_size: $(vm_size)
```

### Auth Methods

All auth is configured under `platform[].azure.credential`. If `credential` is omitted, LISA falls back to `DefaultAzureCredential` (env vars → managed identity → Azure CLI).

| Type | When to use | Required fields |
|------|-------------|----------------|
| *(omit)* | Local dev with `az login`, managed identity, or env vars | — |
| `azcli` | Explicitly use the logged-in `az` CLI session | — |
| `secret` | Service principal with client secret (CI/CD) | `tenant_id`, `client_id`, `client_secret` |
| `certificate` | Service principal with cert | `tenant_id`, `client_id`, `cert_path` |
| `assertion` | Workload identity via MSI + enterprise app | `tenant_id`, `client_id`, `msi_client_id`, `enterprise_app_client_id` |
| `workloadidentity` | OIDC federated workload identity | `tenant_id`, `client_id` |
| `token` | Raw Bearer token | `token` |

**`azcli` (recommended for interactive/local use):**
```yaml
azure:
  subscription_id: $(subscription_id)
  credential:
    type: azcli
```

**Service principal with client secret** — mark `client_secret` as secret:
```yaml
variable:
  - name: client_secret
    is_secret: true
    value: ""
platform:
  - type: azure
    azure:
      subscription_id: $(subscription_id)
      credential:
        type: secret
        tenant_id: $(tenant_id)
        client_id: $(client_id)
        client_secret: $(client_secret)
```

**Workload identity (GitHub Actions / Azure Pipelines OIDC):**
```yaml
azure:
  subscription_id: $(subscription_id)
  credential:
    type: workloadidentity
    tenant_id: $(tenant_id)
    client_id: $(client_id)
```

**Ready (pre-provisioned):**
```yaml
platform:
  - type: ready
environment:
  environments:
    - nodes:
        - type: remote
          address: $(address)
          port: $(port)
          username: $(admin_username)
          password: $(admin_password)
```

---

## Step 4: Testcase Selection

```yaml
testcase:
  - criteria:
      priority: [0, 1]                          # by priority
  - criteria:
      name: verify_sriov_basic|verify_reboot    # by name pattern
  - criteria:
      area: network                              # by area
  - criteria:
      name: verify_ultra_disk
    select_action: exclude                       # exclude
  - criteria:
      priority: 0
    times: 3                                     # repeat
    retry: 2                                     # retry on failure
    use_new_environment: true                    # fresh VM per test
```

---

## Step 5: Common Scenarios

### A. Smoke Test
```yaml
variable:
  - name: marketplace_image
    value: "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"
  - name: location
    value: "westus3"
testcase:
  - criteria:
      name: smoke_test
```

### B. Tier-Based Test
```yaml
include:
  - path: ./tiers/t$(tier).yml
variable:
  - name: tier
    value: 0
```

### C. Security Profile

Security profiles require the **object format** for `marketplace` — the string shorthand does not support them.

```yaml
platform:
  - type: azure
    requirement:
      azure:
        marketplace:
          publisher: "canonical"
          offer: "0001-com-ubuntu-server-jammy"
          sku: "22_04-lts-gen2"
          version: "latest"
          security_profile: ["secureboot"]
```

Valid profiles: `none` (standard/default), `secureboot`, `cvm` (Confidential VM), `stateless`. Profiles other than `none` require Gen2 images.

### D. WSL / Nested Virtualization
```yaml
platform:
  - type: azure
    guest_enabled: true
    guests:
      - type: wsl
        kernel: $(wsl_kernel)
    requirement:
      azure:
        vm_size: "Standard_D4s_v3"
        marketplace:
          publisher: "MicrosoftWindowsServer"
          offer: "WindowsServer"
          sku: "2022-datacenter-g2"
          version: "latest"
          security_profile: ["secureboot"]
testcase:
  - criteria:
      area: wsl
```

### E. Grid Combinator (Multi-Image × Multi-Location)
```yaml
combinator:
  type: grid
  items:
    - name: marketplace_image
      value:
        - "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"
        - "redhat rhel 9_5 latest"
    - name: location
      value: ["westus3", "eastus2"]
testcase:
  - criteria:
      priority: [0, 1]
```

### F. Purchase Plan (ISV Images)
```yaml
platform:
  - type: azure
    requirement:
      azure:
        marketplace:
          publisher: $(plan_publisher)
          offer: $(plan_product)
          sku: $(plan_sku)
          version: "latest"
        purchase_plan:
          name: $(plan_name)
          product: $(plan_product)
          publisher: $(plan_publisher)
```

`hyperv_generation` is optional — LISA auto-detects it from the image's platform tags. Only specify it to override (place inside the marketplace/vhd/shared_gallery object, not at `requirement.azure` level). `purchase_plan` is a node-level property and stays as a sibling to `marketplace`.

### G. Disk & NIC Requirements
```yaml
platform:
  - type: azure
    requirement:
      core_count: { min: 8 }
      memory_mb: { min: 16384 }
      nic_count: { min: 2 }
      disk:
        data_disk_count: { min: 2 }
        data_disk_type: "PremiumSSDLRS"
        disk_controller_type: "NVMe"
      azure:
        marketplace: $(marketplace_image)
```

---

## Step 6: Include Pattern

```yaml
include:
  - path: ./azure.yml              # Inherit base Azure platform config
  - path: ./tiers/t$(tier).yml      # Dynamic tier include via variable
  - path: ./debug.yml               # Debug single test by name
```

Later definitions override earlier ones. CLI variables override everything.
Refer to `lisa/microsoft/runbook/` for available base runbooks.

---

## Rules

1. **Ask the scenario first** — don't guess.
2. **Use variables** for anything the user might change (images, locations, credentials, VM sizes).
3. **Mark secrets**: `is_secret: true` for passwords, subscription IDs, SAS URIs.
4. **Use `include`** for existing base runbooks — don't duplicate. Check `lisa/microsoft/runbook/`.
5. **Security profiles** require Gen2 images and the marketplace **object format** — the 4-part string shorthand does not support them.
6. **Transformer phases** run in order: `init` → `expanded` → `environment_connected` → `expanded_cleanup` → `cleanup`. Use `phase: environment_connected` for transformers that need a provisioned VM (e.g., installing components on the node). `expanded` runs before environments are created.
7. Search `@workspace` for existing runbooks before generating — reuse patterns from `runbook/`.