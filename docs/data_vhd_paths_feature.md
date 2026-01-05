# Data VHD Paths Feature

This feature allows users to specify data disk VHD URIs in the runbook configuration.

## Usage Example

To use data VHD paths in your runbook, add the `data_vhd_paths` field under the `vhd` section:

```yaml
azure:
  shared_gallery: $(shared_gallery)
  marketplace: $(marketplace_image)
  osdisk_size_in_gb: $(osdisk_size_in_gb)
  vhd:
    vhd_path: "https://storageaccount.blob.core.windows.net/container/os.vhd"
    data_vhd_paths:
      - lun: 0
        vhd_uri: "https://storageaccount.blob.core.windows.net/container/data0.vhd"
      - lun: 1
        vhd_uri: "https://storageaccount.blob.core.windows.net/container/data1.vhd"
```

## Requirements

1. **`vhd_path` is required for `data_vhd_paths`**: If you specify `data_vhd_paths`, you must also provide a valid `vhd_path` for the OS disk. If `data_vhd_paths` is provided without `vhd_path`, it will be ignored.

2. **VHD URIs must be valid**: Each VHD URI specified in `data_vhd_paths` will be validated and processed similar to the OS VHD path.

3. **LUN (Logical Unit Number)**: Each data VHD path must have a unique LUN starting from 0.

## Schema Definition

### DataVhdPath

```python
@dataclass
class DataVhdPath:
    lun: int = 0                # Logical Unit Number (0, 1, 2, ...)
    vhd_uri: str = ""          # Full URI to the VHD blob
```

### VhdSchema (Updated)

```python
@dataclass
class VhdSchema(AzureImageSchema):
    vhd_path: str = ""
    cvm_gueststate_path: Optional[str] = None
    cvm_metadata_path: Optional[str] = None
    data_vhd_paths: Optional[List[DataVhdPath]] = None  # NEW FIELD
```

## Processing

When data VHD paths are provided:

1. The system validates that `vhd_path` is also provided (raises `SkippedException` if not)
2. Each `vhd_uri` in `data_vhd_paths` is processed through `get_deployable_storage_path()`:
   - If it's a SAS URL, it will be copied to the deployment region
   - If it's in a different region/subscription, it will be copied
3. Managed disks are created from the VHD URIs in the ARM template
4. The disks are attached to the VM with the specified LUN

## ARM Template Changes

The ARM template now includes:

1. `nodes_data_vhd_disks` resource that creates managed disks from VHD URIs using the "Import" create option
2. Updated `getDataDisk` function to handle Import create option by attaching disks created from VHD URIs
3. Data disks with VHD URIs use the same disk naming convention as other data disks

## Processing Behavior

If `data_vhd_paths` is provided without `vhd_path`, the `data_vhd_paths` will be ignored and the system will proceed with standard data disk creation.

## Example Runbook

Complete example showing VHD usage with data disks:

```yaml
name: vhd_with_data_disks_example
environment:
  nodes:
    - type: remote
      azure:
        vm_size: Standard_DS2_v2
        location: westus3
        vhd:
          vhd_path: "https://mystorageaccount.blob.core.windows.net/vhds/myos.vhd"
          data_vhd_paths:
            - lun: 0
              vhd_uri: "https://mystorageaccount.blob.core.windows.net/vhds/data0.vhd"
            - lun: 1
              vhd_uri: "https://mystorageaccount.blob.core.windows.net/vhds/data1.vhd"
```
