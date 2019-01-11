# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This setup script adds a specified number of NVME disks to a test VM
    It will first search if there are any VMs using NVME disks and detach
    the disk(s). After all the NVME disks are offline and unnasigned to
    VMs, the script will add it/them to the test VM.
#>

param(
    [String] $TestParams, [Object] $AllVMData
)

function Main {
    param (
        $TestParams, $AllVMData
    )
    $currentTestResult = Create-TestResultObject
    try {
        $testResult = $null
        $usableNvmeDiskCount = 0
        $locationPathList = New-Object System.Collections.Generic.List[System.Object]

        # Remove NVME disks from any VM that might use them
        $usedNvmeDisks = Get-VMAssignableDevice *
        foreach ($nvmeDisk in $usedNvmeDisks) {
            $vmNameToBeStopped = $nvmeDisk.VMName
            $locationPath = $nvmeDisk.LocationPath

            if ((Get-VM -ComputerName $allVMData.HypervHost `
                -Name $vmNameToBeStopped).State -ne "Off") {
                # We don't know if the existing VM belongs in a group so we can't
                # use 'Stop-HyperVGroupVMs' function from HyperV.psm1
                Stop-VM -ComputerName $allVMData.HypervHost -Name $vmNameToBeStopped `
                    -Force -Confirm:$false
            }

            Remove-VMAssignableDevice -LocationPath $locationPath `
                -VMName $vmNameToBeStopped
            if (-not $?) {
                throw "Error: Unable to remove NVME disk (VM: $vmNameToBeStopped `
                    : LocationPath $locationPath)"
            }
        }

        # Put all available disks offline and prepare them to be used by a VM
        $activePnpDevs = Get-PnpDevice -PresentOnly -CimSession $allVMData.HypervHost `
            | Where-Object {$_.Class -eq "SCSIAdapter"} | Where-Object {$_.Service -eq "stornvme"}
        foreach ($pnpDev in $activePnpDevs) {
           Disable-PnpDevice -InstanceId $pnpdev.InstanceId -Confirm:$false
           $locationPath = ($pnpdev | Get-PnpDeviceProperty DEVPKEY_Device_LocationPaths).data[0]
           Dismount-VMHostAssignableDevice -locationpath $locationpath
        }

        # Get a list of all usable NVME disks
        $usableNvmeDisks = Get-VMHostAssignableDevice -ComputerName $allVMData.HypervHost
        foreach ($nvmeDisk in $usableNvmeDisks) {
            $locationPathList.Add($nvmeDisk.LocationPath)
            $usableNvmeDiskCount++
        }
        if (-not $TestParams.HYPERV_DISK_COUNT) {
            $diskCount = $usableNvmeDiskCount
        } else {
            $diskCount = $TestParams.HYPERV_DISK_COUNT
        }

        # Stop the test VM
        Stop-HyperVGroupVMs $allVMData.HyperVGroupName $allVMData.HypervHost
        Set-VM -Name $allVMData.RoleName -AutomaticStopAction TurnOff

        # Add the required number of NVME disks
        for ($diskNr=0; $diskNr -lt $diskCount; $diskNr++) {
            Add-VMAssignableDevice -LocationPath $locationPathList[$diskNr] `
                -VMName $allVMData.RoleName
            if (-not $?) {
                throw "Error: Unable to add NVME disk (VM: $($allVMData.RoleName) `
                    : LocationPath $locationPathList[$diskNr])"
            }
        }

        # Start VM and get IP
        $tempIpv4 = Start-VMandGetIP $allVMData.RoleName $allVMData.HypervHost $allVMData.SSHPort `
            $user $password
        if (-not $tempIpv4) {
            throw "Error: Unable to start $($allVMData.RoleName) and get an IPv4 address"
        }

        # Create a file, platform.txt for the test script to know if it runs
        # on Azure or Hyper-V
        $cmdToSend = 'echo "HyperV" > platform.txt'
        Run-LinuxCmd -ip $tempIpv4 -port $allVMData.SSHPort -username $user -password `
            $password -command $cmdToSend
        if (-not $?) {
            throw "Error: Failed to create platform.txt file"
        }
        Write-LogInfo "Successfully configured VM for Hyper-V NVME test"
        $testResult = "PASS"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVMData $AllVMData