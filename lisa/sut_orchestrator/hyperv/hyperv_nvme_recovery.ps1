# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

<#
.SYNOPSIS
Preflights and restores a Hyper-V NVMe DDA device by stable identity.

.DESCRIPTION
ValidateOnly selects or validates one safe NVMe controller and atomically saves
its controller identity, disk identity, and original offline state. A later
invocation uses that state to detach the controller from a VM, return it to the
host, and restore the original disk state after an interrupted LISA run.

.EXAMPLE
.\hyperv_nvme_recovery.ps1 -ValidateOnly -StatePath C:\LISA\nvme-state.json

.EXAMPLE
.\hyperv_nvme_recovery.ps1 -StatePath C:\LISA\nvme-state.json
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string] $LocationPath = "",

    [Parameter(Mandatory = $false)]
    [string] $VMName = "",

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $StatePath,

    [Parameter(Mandatory = $false)]
    [switch] $ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$LocationPath = $LocationPath.Trim()
$VMName = $VMName.Trim()
if ($LocationPath -and
    $LocationPath -notmatch '^PCIROOT\([0-9A-Fa-f]+\)(#PCI\([0-9A-Fa-f]{4}\))+$') {
    throw "Invalid Hyper-V NVMe PCI location path: '$LocationPath'."
}
function Get-PnpLocationPaths {
    param(
        [Parameter(Mandatory = $true)]
        [object] $PnpDevice
    )

    $property = Get-PnpDeviceProperty `
        -InstanceId $PnpDevice.InstanceId `
        -KeyName "DEVPKEY_Device_LocationPaths" `
        -ErrorAction SilentlyContinue
    $dataProperty = if ($null -ne $property) {
        $property.PSObject.Properties["Data"]
    }
    else {
        $null
    }
    if ($null -eq $dataProperty) {
        return @()
    }

    @(
        $dataProperty.Value |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object {
                $_ -match '^PCIROOT\([0-9A-Fa-f]+\)(#PCI\([0-9A-Fa-f]{4}\))+$'
            } |
            Select-Object -Unique
    )
}

function Get-MatchingPnpDevices {
    param(
        [Parameter(Mandatory = $true)]
        [string] $CandidateLocationPath
    )

    @(
        Get-PnpDevice -PresentOnly |
            Where-Object { $_.InstanceId -like "PCI\*" } |
            Where-Object {
                @(Get-PnpLocationPaths -PnpDevice $_) -contains $CandidateLocationPath
            }
    )
}

function Test-NvmeController {
    param(
        [Parameter(Mandatory = $true)]
        [object] $PnpDevice
    )

    $compatibleIdsProperty = Get-PnpDeviceProperty `
        -InstanceId $PnpDevice.InstanceId `
        -KeyName "DEVPKEY_Device_CompatibleIds" `
        -ErrorAction Stop
    @($compatibleIdsProperty.Data) -match '(?i)CC_010802(?:&|$)'
}

function Get-AssignedVMNames {
    param(
        [Parameter(Mandatory = $true)]
        [string] $CandidateLocationPath
    )

    @(
        Get-VM | ForEach-Object {
            $vm = $_
            Get-VMAssignableDevice `
                -VMName $vm.Name `
                -ErrorAction Stop |
                Where-Object {
                    [string]::Equals(
                        $_.LocationPath,
                        $CandidateLocationPath,
                        [System.StringComparison]::OrdinalIgnoreCase
                    )
                } |
                ForEach-Object { $vm.Name }
        }
    )
}

function Test-DiskInStoragePool {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Disk
    )

    $diskUniqueId = ([string]$Disk.UniqueId).Trim()
    $diskSerialNumber = ([string]$Disk.SerialNumber).Trim()
    $diskNumber = ([string]$Disk.Number).Trim()
    $physicalDisks = @(
        Get-PhysicalDisk -ErrorAction Stop |
            Where-Object {
                $physicalUniqueId = ([string]$_.UniqueId).Trim()
                $physicalSerialNumber = ([string]$_.SerialNumber).Trim()
                $physicalDeviceId = ([string]$_.DeviceId).Trim()
                ($diskUniqueId -and [string]::Equals(
                    $diskUniqueId,
                    $physicalUniqueId,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) -or
                ($diskSerialNumber -and [string]::Equals(
                    $diskSerialNumber,
                    $physicalSerialNumber,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) -or
                ($physicalDeviceId -eq $diskNumber)
            }
    )
    if ($physicalDisks.Count -ne 1) {
        throw "Windows NVMe disk $($Disk.Number) mapped to $($physicalDisks.Count) physical disks."
    }

    $nonPrimordialPools = @(
        Get-StoragePool `
            -PhysicalDisk $physicalDisks[0] `
            -ErrorAction Stop |
            Where-Object { -not $_.IsPrimordial }
    )
    return $nonPrimordialPools.Count -gt 0
}

function New-NvmeRecoveryState {
    param(
        [Parameter(Mandatory = $true)]
        [object] $PnpDevice,

        [Parameter(Mandatory = $true)]
        [string] $CandidateLocationPath
    )

    $pending = [System.Collections.Generic.Queue[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $pending.Enqueue([string]$PnpDevice.InstanceId)
    while ($pending.Count -gt 0) {
        $currentId = $pending.Dequeue()
        if (-not $seen.Add($currentId)) {
            continue
        }

        $childrenProperty = Get-PnpDeviceProperty `
            -InstanceId $currentId `
            -KeyName "DEVPKEY_Device_Children" `
            -ErrorAction SilentlyContinue
        $childrenDataProperty = if ($null -ne $childrenProperty) {
            $childrenProperty.PSObject.Properties["Data"]
        }
        else {
            $null
        }
        if ($currentId -eq $PnpDevice.InstanceId -and
            $null -eq $childrenDataProperty) {
            throw "Could not query PnP children for NVMe controller '$currentId'."
        }
        if ($null -ne $childrenDataProperty) {
            foreach ($childId in @($childrenDataProperty.Value)) {
                if ($childId) {
                    $pending.Enqueue([string]$childId)
                }
            }
        }
    }

    $diskDrives = @(
        Get-CimInstance Win32_DiskDrive -ErrorAction Stop |
            Where-Object { $seen.Contains([string]$_.PNPDeviceID) }
    )
    if ($diskDrives.Count -ne 1) {
        throw "Hyper-V NVMe location path '$CandidateLocationPath' mapped to $($diskDrives.Count) Windows disks."
    }

    $disk = Get-Disk -Number ([int]$diskDrives[0].Index) -ErrorAction Stop
    if ([string]$disk.BusType -ne "NVMe") {
        throw "Disk $($disk.Number) for '$CandidateLocationPath' has bus type '$($disk.BusType)', expected 'NVMe'."
    }
    if ($disk.IsBoot -or $disk.IsSystem) {
        throw "Disk $($disk.Number) for '$CandidateLocationPath' is a boot or system disk."
    }

    $accessPaths = @(
        Get-CimInstance `
            -Namespace ROOT/Microsoft/Windows/Storage `
            -ClassName MSFT_Partition `
            -Filter "DiskNumber = $($disk.Number)" `
            -ErrorAction Stop |
            ForEach-Object { @($_.AccessPaths) } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($accessPaths.Count -gt 0) {
        throw "Disk $($disk.Number) for '$CandidateLocationPath' has mounted access paths."
    }
    if (Test-DiskInStoragePool -Disk $disk) {
        throw "Disk $($disk.Number) for '$CandidateLocationPath' belongs to a non-primordial storage pool."
    }

    $uniqueId = ([string]$disk.UniqueId).Trim()
    $serialNumber = ([string]$disk.SerialNumber).Trim()
    if (-not $uniqueId -and -not $serialNumber) {
        throw "Windows NVMe disk for '$CandidateLocationPath' has no stable identity."
    }

    [PSCustomObject]@{
        LocationPath = $CandidateLocationPath
        InstanceId = [string]$PnpDevice.InstanceId
        DiskNumber = [int]$disk.Number
        UniqueId = $uniqueId
        SerialNumber = $serialNumber
        WasOffline = [bool]$disk.IsOffline
    }
}

function Find-SafeNvmeRecoveryState {
    $nvmeControllers = @(
        Get-PnpDevice -PresentOnly |
            Where-Object {
                $_.InstanceId -like "PCI\*" -and
                $_.Class -eq "SCSIAdapter"
            } |
            Where-Object { Test-NvmeController -PnpDevice $_ }
    )
    $eligible = @()
    $rejected = @()

    foreach ($controller in $nvmeControllers) {
        $controllerPaths = @(Get-PnpLocationPaths -PnpDevice $controller)
        if ($controllerPaths.Count -eq 0) {
            $rejected += "$($controller.InstanceId): no PCI location path"
            continue
        }

        $candidatePath = $controllerPaths[0]
        try {
            $assignedVMs = @(Get-AssignedVMNames -CandidateLocationPath $candidatePath)
            if ($assignedVMs.Count -gt 0) {
                throw "device is assigned to VM(s): $($assignedVMs -join ', ')"
            }
            $eligible += New-NvmeRecoveryState `
                -PnpDevice $controller `
                -CandidateLocationPath $candidatePath
        }
        catch {
            $rejected += "${candidatePath}: $($_.Exception.Message)"
        }
    }

    if ($eligible.Count -ne 1) {
        $eligibleSummary = if ($eligible.Count -gt 0) {
            ($eligible | ForEach-Object {
                "$($_.LocationPath) (disk $($_.DiskNumber))"
            }) -join ", "
        }
        else {
            "none"
        }
        $rejectedSummary = if ($rejected.Count -gt 0) {
            $rejected -join "; "
        }
        else {
            "none"
        }
        throw "Expected exactly one safe Hyper-V NVMe passthrough candidate, found $($eligible.Count). Eligible: $eligibleSummary. Rejected: $rejectedSummary."
    }

    return $eligible[0]
}

function Get-NvmeRecoveryState {
    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
        throw "Hyper-V NVMe recovery state was not found at '$StatePath'."
    }

    $state = Get-Content -LiteralPath $StatePath -Raw -ErrorAction Stop |
        ConvertFrom-Json -ErrorAction Stop
    foreach ($propertyName in @(
        "LocationPath",
        "InstanceId",
        "UniqueId",
        "SerialNumber",
        "WasOffline"
    )) {
        if ($null -eq $state.PSObject.Properties[$propertyName]) {
            throw "Hyper-V NVMe recovery state is missing '$propertyName'."
        }
    }
    if (-not ([string]$state.UniqueId).Trim() -and
        -not ([string]$state.SerialNumber).Trim()) {
        throw "Hyper-V NVMe recovery state has no stable disk identity."
    }
    return $state
}

function Assert-NvmeRecoveryIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Expected,

        [Parameter(Mandatory = $true)]
        [object] $Actual
    )

    foreach ($propertyName in @("LocationPath", "InstanceId", "UniqueId", "SerialNumber")) {
        $expectedValue = ([string]$Expected.$propertyName).Trim()
        if ($expectedValue -and -not [string]::Equals(
            $expectedValue,
            ([string]$Actual.$propertyName).Trim(),
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Hyper-V NVMe recovery identity mismatch for '$propertyName'."
        }
    }
}

function Save-NvmeRecoveryState {
    param(
        [Parameter(Mandatory = $true)]
        [object] $State
    )

    if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
        $savedState = Get-NvmeRecoveryState
        Assert-NvmeRecoveryIdentity -Expected $savedState -Actual $State
        return
    }

    $stateDirectory = Split-Path -Parent $StatePath
    if (-not $stateDirectory) {
        $stateDirectory = "."
    }
    if (-not (Test-Path -LiteralPath $stateDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $stateDirectory -Force -ErrorAction Stop |
            Out-Null
    }
    $temporaryStatePath = Join-Path `
        $stateDirectory `
        (".{0}.{1}.tmp" -f (
            Split-Path -Leaf $StatePath
        ), [guid]::NewGuid().ToString("N"))
    try {
        $State |
            ConvertTo-Json -Compress |
            Set-Content `
                -LiteralPath $temporaryStatePath `
                -Encoding UTF8 `
                -ErrorAction Stop
        Move-Item `
            -LiteralPath $temporaryStatePath `
            -Destination $StatePath `
            -Force `
            -ErrorAction Stop
    }
    finally {
        Remove-Item `
            -LiteralPath $temporaryStatePath `
            -Force `
            -ErrorAction SilentlyContinue
    }
}

function Get-DisksByRecoveryState {
    param(
        [Parameter(Mandatory = $true)]
        [object] $State
    )

    $expectedUniqueId = ([string]$State.UniqueId).Trim()
    $expectedSerialNumber = ([string]$State.SerialNumber).Trim()
    Get-Disk -ErrorAction SilentlyContinue |
        Where-Object {
            $uniqueIdMatches = -not $expectedUniqueId -or [string]::Equals(
                ([string]$_.UniqueId).Trim(),
                $expectedUniqueId,
                [System.StringComparison]::OrdinalIgnoreCase
            )
            $serialNumberMatches = -not $expectedSerialNumber -or [string]::Equals(
                ([string]$_.SerialNumber).Trim(),
                $expectedSerialNumber,
                [System.StringComparison]::OrdinalIgnoreCase
            )
            $uniqueIdMatches -and $serialNumberMatches
        }
}

if ($ValidateOnly) {
    if ($LocationPath) {
        $assignedVMs = @(Get-AssignedVMNames -CandidateLocationPath $LocationPath)
        if ($assignedVMs.Count -gt 0) {
            throw "Hyper-V NVMe device '$LocationPath' is already assigned to VM(s): $($assignedVMs -join ', ')."
        }
        $matchingDevices = @(Get-MatchingPnpDevices -CandidateLocationPath $LocationPath)
        if ($matchingDevices.Count -ne 1) {
            throw "Hyper-V NVMe location path '$LocationPath' mapped to $($matchingDevices.Count) PnP devices during preflight."
        }
        $currentState = New-NvmeRecoveryState `
            -PnpDevice $matchingDevices[0] `
            -CandidateLocationPath $LocationPath
    }
    else {
        $currentState = Find-SafeNvmeRecoveryState
        $LocationPath = [string]$currentState.LocationPath
        Write-Host "Auto-discovered Hyper-V NVMe location path '$LocationPath'."
    }

    Save-NvmeRecoveryState -State $currentState
    $persistedState = Get-NvmeRecoveryState
    Write-Output "NVME_LOCATION_PATH=$LocationPath"
    Write-Host "Hyper-V NVMe recovery preflight passed for '$LocationPath'; original disk offline state is '$($persistedState.WasOffline)'."
    return
}

$recoveryState = Get-NvmeRecoveryState
if (-not $VMName) {
    throw "VMName is required for Hyper-V NVMe recovery."
}
if ($LocationPath) {
    if (-not [string]::Equals(
        $LocationPath,
        [string]$recoveryState.LocationPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Hyper-V NVMe recovery state location does not match '$LocationPath'."
    }
}
else {
    $LocationPath = [string]$recoveryState.LocationPath
}

$assignedVMs = @(Get-AssignedVMNames -CandidateLocationPath $LocationPath)
if ($assignedVMs.Count -gt 1) {
    throw "Hyper-V NVMe device '$LocationPath' is assigned to multiple VMs: $($assignedVMs -join ', ')."
}
if ($VMName -and $assignedVMs.Count -eq 1 -and
    -not [string]::Equals(
        $VMName,
        $assignedVMs[0],
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Hyper-V NVMe device '$LocationPath' is assigned to unexpected VM '$($assignedVMs[0])', expected '$VMName'."
}
foreach ($assignedVM in $assignedVMs) {
    $vm = Get-VM -Name $assignedVM -ErrorAction Stop
    if ($vm.State -ne "Off") {
        Stop-VM -Name $assignedVM -Force -TurnOff -ErrorAction Stop
        $vmIsOff = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            $vm = Get-VM -Name $assignedVM -ErrorAction Stop
            if ($vm.State -eq "Off") {
                $vmIsOff = $true
                break
            }
            if ($attempt -lt 29) {
                Start-Sleep -Seconds 1
            }
        }
        if (-not $vmIsOff) {
            throw "Hyper-V VM '$assignedVM' did not stop within 30 seconds."
        }
    }
    Remove-VMAssignableDevice `
        -LocationPath $LocationPath `
        -VMName $assignedVM `
        -ErrorAction Stop
}
if ($assignedVMs.Count -eq 1) {
    $remainingAssignments = @(
        Get-AssignedVMNames -CandidateLocationPath $LocationPath
    )
    if ($remainingAssignments.Count -gt 0) {
        throw "Hyper-V NVMe device '$LocationPath' is still assigned after removal."
    }
}

$mountError = $null
try {
    Mount-VMHostAssignableDevice -LocationPath $LocationPath -ErrorAction Stop
}
catch {
    $mountError = $_
}

$matchingDevices = @(Get-MatchingPnpDevices -CandidateLocationPath $LocationPath)
if ($matchingDevices.Count -ne 1) {
    throw "Hyper-V NVMe location path '$LocationPath' mapped to $($matchingDevices.Count) PnP devices during restoration."
}
$device = $matchingDevices[0]
if (-not [string]::Equals(
    [string]$device.InstanceId,
    [string]$recoveryState.InstanceId,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Hyper-V NVMe controller identity changed during restoration."
}

$configManagerErrorCode = "$($device.ConfigManagerErrorCode)".Trim()
if ($configManagerErrorCode -in @("22", "CM_PROB_DISABLED")) {
    Enable-PnpDevice -InstanceId $device.InstanceId -Confirm:$false -ErrorAction Stop
}

$deviceEnabled = $false
$deadline = (Get-Date).AddSeconds(30)
do {
    $device = Get-PnpDevice -PresentOnly -InstanceId $device.InstanceId -ErrorAction Stop
    $configManagerErrorCode = "$($device.ConfigManagerErrorCode)".Trim()
    if ($configManagerErrorCode -in @("0", "CM_PROB_NONE")) {
        $deviceEnabled = $true
        break
    }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

if (-not $deviceEnabled) {
    throw "Hyper-V NVMe device '$LocationPath' was not enabled within 30 seconds. Last ConfigManagerErrorCode: $($device.ConfigManagerErrorCode)"
}
if ($mountError) {
    Write-Warning "Mount reported an error, but the NVMe device is enabled: $($mountError.Exception.Message)"
}

$matchingDisks = @()
$deadline = (Get-Date).AddSeconds(30)
do {
    $matchingDisks = @(Get-DisksByRecoveryState -State $recoveryState)
    if ($matchingDisks.Count -gt 1) {
        throw "Hyper-V NVMe recovery disk identity is ambiguous."
    }
    if ($matchingDisks.Count -eq 1) {
        break
    }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

if ($matchingDisks.Count -ne 1) {
    throw "Hyper-V NVMe recovery disk did not reappear within 30 seconds."
}

$desiredOffline = [System.Convert]::ToBoolean($recoveryState.WasOffline)
$disk = $matchingDisks[0]
if ([bool]$disk.IsOffline -ne $desiredOffline) {
    Set-Disk -InputObject $disk -IsOffline $desiredOffline -ErrorAction Stop
}
$restoredDisk = Get-Disk -Number $disk.Number -ErrorAction Stop
if ([bool]$restoredDisk.IsOffline -ne $desiredOffline) {
    throw "Hyper-V NVMe disk did not return to its original offline state '$desiredOffline'."
}

Write-Host "Restored Hyper-V NVMe device '$LocationPath' and disk state to the host."