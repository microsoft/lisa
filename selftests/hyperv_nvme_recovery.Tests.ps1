# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

Describe "Hyper-V NVMe recovery" {
    BeforeAll {
        function Get-PnpDevice { throw "Get-PnpDevice must be mocked." }
        function Get-PnpDeviceProperty {
            throw "Get-PnpDeviceProperty must be mocked."
        }
        function Get-VM { throw "Get-VM must be mocked." }
        function Get-VMAssignableDevice {
            throw "Get-VMAssignableDevice must be mocked."
        }
        function Get-StoragePool { throw "Get-StoragePool must be mocked." }
        function Get-PhysicalDisk { throw "Get-PhysicalDisk must be mocked." }
        function Get-CimInstance { throw "Get-CimInstance must be mocked." }
        function Get-Disk { throw "Get-Disk must be mocked." }
        function Mount-VMHostAssignableDevice {
            throw "Mount-VMHostAssignableDevice must be mocked."
        }
        function Stop-VM { throw "Stop-VM must be mocked." }
        function Remove-VMAssignableDevice {
            throw "Remove-VMAssignableDevice must be mocked."
        }
        function Enable-PnpDevice { throw "Enable-PnpDevice must be mocked." }
        function Set-Disk { throw "Set-Disk must be mocked." }

        $scriptPath = Join-Path `
            $PSScriptRoot `
            "..\lisa\sut_orchestrator\hyperv\hyperv_nvme_recovery.ps1"
        $expectedLocationPath = "PCIROOT(5D)#PCI(0000)#PCI(0000)"
        $controllerId = "PCI\VEN_144D&DEV_A80A"
        $diskId = "SCSI\DISK&VEN_NVME"
    }

    BeforeEach {
        Mock Get-VM { @() }
        Mock Get-VMAssignableDevice { @() }
        Mock Get-StoragePool { @() }
        Mock Get-PhysicalDisk { @() }
    }

    It "auto-discovers one safe raw disk and preserves recovery state" {
        $statePath = Join-Path $TestDrive "nvme-state.json"
        $diskState = @{ IsOffline = $false }
        $diskIdentity = @{
            UniqueId = "disk-unique-id"
            SerialNumber = "disk-serial"
        }
        Mock Get-PnpDevice {
            [PSCustomObject]@{
                InstanceId = $controllerId
                Class = "SCSIAdapter"
                FriendlyName = "Vendor Storage Controller"
                ConfigManagerErrorCode = 0
            }
        }
        Mock Get-PnpDeviceProperty {
            param($InstanceId, $KeyName)

            if ($KeyName -eq "DEVPKEY_Device_LocationPaths") {
                [PSCustomObject]@{ Data = @($expectedLocationPath) }
            }
            elseif ($KeyName -eq "DEVPKEY_Device_CompatibleIds") {
                [PSCustomObject]@{ Data = @("PCI\CC_010802") }
            }
            else {
                [PSCustomObject]@{ Data = @($diskId) }
            }
        }
        Mock Get-CimInstance {
            param($ClassName, $Namespace, $Filter)

            if ($Namespace -eq "ROOT/Microsoft/Windows/Storage") {
                $ClassName | Should -Be "MSFT_Partition"
                $Filter | Should -Be "DiskNumber = 4"
                return @()
            }
            [PSCustomObject]@{ PNPDeviceID = $diskId; Index = 4 }
        }
        Mock Get-Disk {
            param($Number)

            [PSCustomObject]@{
                Number = 4
                UniqueId = $diskIdentity.UniqueId
                SerialNumber = $diskIdentity.SerialNumber
                BusType = "NVMe"
                IsBoot = $false
                IsSystem = $false
                IsOffline = $diskState.IsOffline
            }
        }
        Mock Get-PhysicalDisk {
            [PSCustomObject]@{
                DeviceId = "4"
                UniqueId = $diskIdentity.UniqueId
                SerialNumber = $diskIdentity.SerialNumber
            }
        }

        $output = & $scriptPath -ValidateOnly -StatePath $statePath

        $output | Should -Contain "NVME_LOCATION_PATH=$expectedLocationPath"
        $savedState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $savedState.LocationPath | Should -Be $expectedLocationPath
        $savedState.InstanceId | Should -Be $controllerId
        $savedState.UniqueId | Should -Be "disk-unique-id"
        $savedState.SerialNumber | Should -Be "disk-serial"
        $savedState.WasOffline | Should -BeFalse

        $diskState.IsOffline = $true
        & $scriptPath -ValidateOnly -StatePath $statePath
        $preservedState = Get-Content -LiteralPath $statePath -Raw |
            ConvertFrom-Json
        $preservedState.WasOffline | Should -BeFalse

        $diskIdentity.UniqueId = "replacement-unique-id"
        $diskIdentity.SerialNumber = "replacement-serial"
        {
            & $scriptPath -ValidateOnly -StatePath $statePath
        } | Should -Throw -ExpectedMessage "*identity mismatch*"
        $unchangedState = Get-Content -LiteralPath $statePath -Raw |
            ConvertFrom-Json
        $unchangedState.UniqueId | Should -Be "disk-unique-id"
        $unchangedState.SerialNumber | Should -Be "disk-serial"

        $diskIdentity.UniqueId = "disk-unique-id"
        $diskIdentity.SerialNumber = "disk-serial"

        $failedStatePath = Join-Path $TestDrive "partition-query-failed.json"
        Mock Get-CimInstance {
            param($ClassName, $Namespace, $Filter)

            if ($Namespace -eq "ROOT/Microsoft/Windows/Storage") {
                $ClassName | Should -Be "MSFT_Partition"
                $Filter | Should -Be "DiskNumber = 4"
                throw "partition inventory unavailable"
            }
            [PSCustomObject]@{ PNPDeviceID = $diskId; Index = 4 }
        }
        {
            & $scriptPath -ValidateOnly -StatePath $failedStatePath
        } | Should -Throw -ExpectedMessage "*found 0*partition inventory unavailable*"
        $failedStatePath | Should -Not -Exist
    }

    It "rejects unsafe disks without saving recovery state" {
        $diskState = @{
            BusType = "NVMe"
            IsBoot = $false
            IsSystem = $false
            AccessPaths = @()
            InStoragePool = $false
        }
        Mock Get-PnpDevice {
            [PSCustomObject]@{
                InstanceId = $controllerId
                Class = "SCSIAdapter"
                FriendlyName = "Vendor Storage Controller"
            }
        }
        Mock Get-PnpDeviceProperty {
            param($InstanceId, $KeyName)

            if ($KeyName -eq "DEVPKEY_Device_LocationPaths") {
                [PSCustomObject]@{ Data = @($expectedLocationPath) }
            }
            elseif ($KeyName -eq "DEVPKEY_Device_CompatibleIds") {
                [PSCustomObject]@{ Data = @("PCI\CC_010802") }
            }
            else {
                [PSCustomObject]@{ Data = @($diskId) }
            }
        }
        Mock Get-CimInstance {
            param($ClassName, $Namespace, $Filter)

            if ($Namespace -eq "ROOT/Microsoft/Windows/Storage") {
                $ClassName | Should -Be "MSFT_Partition"
                $Filter | Should -Be "DiskNumber = 4"
                if ($diskState.AccessPaths.Count -eq 0) {
                    return @()
                }
                return @(
                    [PSCustomObject]@{ AccessPaths = @() },
                    [PSCustomObject]@{
                        AccessPaths = @($diskState.AccessPaths)
                    }
                )
            }
            [PSCustomObject]@{ PNPDeviceID = $diskId; Index = 4 }
        }
        Mock Get-Disk {
            [PSCustomObject]@{
                Number = 4
                UniqueId = "disk-unique-id"
                SerialNumber = "disk-serial"
                BusType = $diskState.BusType
                IsBoot = $diskState.IsBoot
                IsSystem = $diskState.IsSystem
                IsOffline = $false
            }
        }
        Mock Get-PhysicalDisk {
            [PSCustomObject]@{
                DeviceId = "4"
                UniqueId = "disk-unique-id"
                SerialNumber = "disk-serial"
            }
        }
        Mock Get-StoragePool {
            if ($diskState.InStoragePool) {
                [PSCustomObject]@{ IsPrimordial = $false }
            }
            else {
                @()
            }
        }

        $scenarios = @(
            @{
                Name = "non-nvme"
                BusType = "RAID"
                IsBoot = $false
                IsSystem = $false
                AccessPaths = @()
                InStoragePool = $false
                ExpectedMessage = "*expected 'NVMe'*"
            },
            @{
                Name = "boot"
                BusType = "NVMe"
                IsBoot = $true
                IsSystem = $false
                AccessPaths = @()
                InStoragePool = $false
                ExpectedMessage = "*boot or system disk*"
            },
            @{
                Name = "mounted"
                BusType = "NVMe"
                IsBoot = $false
                IsSystem = $false
                AccessPaths = @("D:\")
                InStoragePool = $false
                ExpectedMessage = "*mounted access paths*"
            },
            @{
                Name = "storage-pool"
                BusType = "NVMe"
                IsBoot = $false
                IsSystem = $false
                AccessPaths = @()
                InStoragePool = $true
                ExpectedMessage = "*non-primordial storage pool*"
            }
        )
        foreach ($scenario in $scenarios) {
            $diskState.BusType = $scenario.BusType
            $diskState.IsBoot = $scenario.IsBoot
            $diskState.IsSystem = $scenario.IsSystem
            $diskState.AccessPaths = $scenario.AccessPaths
            $diskState.InStoragePool = $scenario.InStoragePool
            $statePath = Join-Path $TestDrive "$($scenario.Name)-state.json"

            {
                & $scriptPath -ValidateOnly -StatePath $statePath
            } | Should -Throw -ExpectedMessage $scenario.ExpectedMessage
            $statePath | Should -Not -Exist
        }
    }

    It "rejects multiple safe controllers without saving state" {
        $statePath = Join-Path $TestDrive "ambiguous-state.json"
        $secondControllerId = "PCI\VEN_144D&DEV_A80B"
        $secondDiskId = "SCSI\DISK&VEN_NVME2"
        $secondLocationPath = "PCIROOT(5D)#PCI(0001)#PCI(0000)"
        Mock Get-PnpDevice {
            @(
                [PSCustomObject]@{
                    InstanceId = $controllerId
                    Class = "SCSIAdapter"
                    FriendlyName = "Standard NVM Express Controller"
                },
                [PSCustomObject]@{
                    InstanceId = $secondControllerId
                    Class = "SCSIAdapter"
                    FriendlyName = "NVMe Controller"
                }
            )
        }
        Mock Get-PnpDeviceProperty {
            param($InstanceId, $KeyName)

            if ($KeyName -eq "DEVPKEY_Device_LocationPaths") {
                $path = if ($InstanceId -eq $controllerId) {
                    $expectedLocationPath
                }
                else {
                    $secondLocationPath
                }
                [PSCustomObject]@{ Data = @($path) }
            }
            elseif ($KeyName -eq "DEVPKEY_Device_CompatibleIds") {
                [PSCustomObject]@{ Data = @("PCI\CC_010802") }
            }
            elseif ($InstanceId -eq $controllerId) {
                [PSCustomObject]@{ Data = @($diskId) }
            }
            elseif ($InstanceId -eq $secondControllerId) {
                [PSCustomObject]@{ Data = @($secondDiskId) }
            }
            else {
                [PSCustomObject]@{ Data = @() }
            }
        }
        Mock Get-CimInstance {
            param($ClassName, $Namespace, $Filter)

            if ($Namespace -eq "ROOT/Microsoft/Windows/Storage") {
                $ClassName | Should -Be "MSFT_Partition"
                $Filter | Should -BeIn @("DiskNumber = 4", "DiskNumber = 5")
                return @()
            }
            @(
                [PSCustomObject]@{ PNPDeviceID = $diskId; Index = 4 },
                [PSCustomObject]@{ PNPDeviceID = $secondDiskId; Index = 5 }
            )
        }
        Mock Get-Disk {
            param($Number)

            [PSCustomObject]@{
                Number = $Number
                UniqueId = "disk-unique-id-$Number"
                SerialNumber = "disk-serial-$Number"
                BusType = "NVMe"
                IsBoot = $false
                IsSystem = $false
                IsOffline = $false
            }
        }
        Mock Get-PhysicalDisk {
            @(
                [PSCustomObject]@{
                    DeviceId = "4"
                    UniqueId = "disk-unique-id-4"
                    SerialNumber = "disk-serial-4"
                },
                [PSCustomObject]@{
                    DeviceId = "5"
                    UniqueId = "disk-unique-id-5"
                    SerialNumber = "disk-serial-5"
                }
            )
        }

        {
            & $scriptPath -ValidateOnly -StatePath $statePath
        } | Should -Throw -ExpectedMessage "*exactly one*found 2*"
        $statePath | Should -Not -Exist
    }

    It "rejects a device assigned to an unexpected VM before detaching it" {
        $statePath = Join-Path $TestDrive "unexpected-vm-state.json"
        [PSCustomObject]@{
            LocationPath = $expectedLocationPath
            InstanceId = $controllerId
            DiskNumber = 4
            UniqueId = "disk-unique-id"
            SerialNumber = "disk-serial"
            WasOffline = $false
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath

        Mock Get-VM {
            [PSCustomObject]@{ Name = "unrelated-vm"; State = "Running" }
        }
        Mock Get-VMAssignableDevice {
            [PSCustomObject]@{ LocationPath = $expectedLocationPath }
        }
        Mock Stop-VM {}
        Mock Remove-VMAssignableDevice {}

        {
            & $scriptPath `
                -StatePath $statePath `
                -VMName "expected-vm"
        } | Should -Throw -ExpectedMessage "*unexpected VM 'unrelated-vm'*"
        Should -Invoke Stop-VM -Times 0 -Exactly
        Should -Invoke Remove-VMAssignableDevice -Times 0 -Exactly
    }

    It "fails closed when VM assignment inventory cannot be queried" {
        $statePath = Join-Path $TestDrive "inventory-error-state.json"
        Mock Get-VM {
            [PSCustomObject]@{ Name = "expected-vm"; State = "Off" }
        }
        Mock Get-VMAssignableDevice { throw "assignment inventory unavailable" }
        Mock Remove-VMAssignableDevice {}

        {
            & $scriptPath `
                -ValidateOnly `
                -LocationPath $expectedLocationPath `
                -StatePath $statePath
        } | Should -Throw -ExpectedMessage "*assignment inventory unavailable*"
        Should -Invoke Remove-VMAssignableDevice -Times 0 -Exactly
        $statePath | Should -Not -Exist
    }

    It "requires the expected VM name before recovery" {
        $statePath = Join-Path $TestDrive "missing-vm-state.json"
        [PSCustomObject]@{
            LocationPath = $expectedLocationPath
            InstanceId = $controllerId
            DiskNumber = 4
            UniqueId = "disk-unique-id"
            SerialNumber = "disk-serial"
            WasOffline = $false
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath
        Mock Remove-VMAssignableDevice {}

        {
            & $scriptPath -StatePath $statePath
        } | Should -Throw -ExpectedMessage "*VMName is required*"
        Should -Invoke Remove-VMAssignableDevice -Times 0 -Exactly
    }

    It "rejects incomplete recovery state before changing device ownership" {
        $statePath = Join-Path $TestDrive "incomplete-state.json"
        [PSCustomObject]@{
            LocationPath = $expectedLocationPath
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath
        Mock Remove-VMAssignableDevice {}
        Mock Mount-VMHostAssignableDevice {}

        {
            & $scriptPath -StatePath $statePath -VMName "expected-vm"
        } | Should -Throw -ExpectedMessage "*missing 'InstanceId'*"
        Should -Invoke Remove-VMAssignableDevice -Times 0 -Exactly
        Should -Invoke Mount-VMHostAssignableDevice -Times 0 -Exactly
    }

    It "does not detach a device until the expected VM is off" {
        $statePath = Join-Path $TestDrive "running-vm-state.json"
        [PSCustomObject]@{
            LocationPath = $expectedLocationPath
            InstanceId = $controllerId
            DiskNumber = 4
            UniqueId = "disk-unique-id"
            SerialNumber = "disk-serial"
            WasOffline = $false
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath
        Mock Get-VM {
            [PSCustomObject]@{ Name = "expected-vm"; State = "Running" }
        }
        Mock Get-VMAssignableDevice {
            [PSCustomObject]@{ LocationPath = $expectedLocationPath }
        }
        Mock Stop-VM {}
        Mock Start-Sleep {}
        Mock Remove-VMAssignableDevice {}

        {
            & $scriptPath `
                -StatePath $statePath `
                -VMName "expected-vm"
        } | Should -Throw -ExpectedMessage "*did not stop within 30 seconds*"
        Should -Invoke Stop-VM -Times 1 -Exactly
        Should -Invoke Remove-VMAssignableDevice -Times 0 -Exactly
    }

    It "does not mount a device that remains assigned after removal" {
        $statePath = Join-Path $TestDrive "still-assigned-state.json"
        [PSCustomObject]@{
            LocationPath = $expectedLocationPath
            InstanceId = $controllerId
            DiskNumber = 4
            UniqueId = "disk-unique-id"
            SerialNumber = "disk-serial"
            WasOffline = $false
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath
        Mock Get-VM {
            [PSCustomObject]@{ Name = "expected-vm"; State = "Off" }
        }
        Mock Get-VMAssignableDevice {
            [PSCustomObject]@{ LocationPath = $expectedLocationPath }
        }
        Mock Remove-VMAssignableDevice {}
        Mock Mount-VMHostAssignableDevice {}

        {
            & $scriptPath `
                -StatePath $statePath `
                -VMName "expected-vm"
        } | Should -Throw -ExpectedMessage "*still assigned after removal*"
        Should -Invoke Remove-VMAssignableDevice -Times 1 -Exactly
        Should -Invoke Mount-VMHostAssignableDevice -Times 0 -Exactly
    }

    It "rejects a changed controller identity before enabling the device" {
        $statePath = Join-Path $TestDrive "controller-mismatch-state.json"
        [PSCustomObject]@{
            LocationPath = $expectedLocationPath
            InstanceId = $controllerId
            DiskNumber = 4
            UniqueId = "disk-unique-id"
            SerialNumber = "disk-serial"
            WasOffline = $false
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath

        Mock Mount-VMHostAssignableDevice {}
        Mock Get-PnpDevice {
            [PSCustomObject]@{
                InstanceId = "PCI\VEN_144D&DEV_REPLACED"
                Class = "SCSIAdapter"
                ConfigManagerErrorCode = 22
            }
        }
        Mock Get-PnpDeviceProperty {
            [PSCustomObject]@{ Data = @($expectedLocationPath) }
        }
        Mock Enable-PnpDevice {}
        Mock Set-Disk {}

        {
            & $scriptPath -StatePath $statePath -VMName "expected-vm"
        } | Should -Throw -ExpectedMessage "*controller identity changed*"
        Should -Invoke Enable-PnpDevice -Times 0 -Exactly
        Should -Invoke Set-Disk -Times 0 -Exactly
    }

    It "restores the exact disk state" {
        $statePath = Join-Path $TestDrive "restore-state.json"
        [PSCustomObject]@{
            LocationPath = $expectedLocationPath
            InstanceId = $controllerId
            DiskNumber = 4
            UniqueId = "disk-unique-id"
            SerialNumber = "disk-serial"
            WasOffline = $false
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath

        $diskState = @{ IsOffline = $true }
        Mock Mount-VMHostAssignableDevice {}
        Mock Enable-PnpDevice {}
        Mock Get-PnpDevice {
            [PSCustomObject]@{
                InstanceId = $controllerId
                Class = "SCSIAdapter"
                FriendlyName = "Standard NVM Express Controller"
                ConfigManagerErrorCode = 0
            }
        }
        Mock Get-PnpDeviceProperty {
            [PSCustomObject]@{ Data = @($expectedLocationPath) }
        }
        Mock Get-Disk {
            param($Number)

            [PSCustomObject]@{
                Number = 4
                UniqueId = "disk-unique-id"
                SerialNumber = "disk-serial"
                BusType = "NVMe"
                IsBoot = $false
                IsSystem = $false
                IsOffline = $diskState.IsOffline
            }
        }
        Mock Set-Disk {
            param($InputObject, $IsOffline)

            $diskState.IsOffline = [bool]$IsOffline
        }

        & $scriptPath -StatePath $statePath -VMName "expected-vm"

        Should -Invoke Set-Disk -Times 1 -Exactly
        $diskState.IsOffline | Should -BeFalse
    }
}