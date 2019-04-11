# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests VSS backup functionality.
.Description
    This script will create a new VM with a 3-chained differencing disk
    attached based on the source vm vhd/x.
    If the source Vm has more than 1 snapshot, they will be removed except
    the latest one. If the VM has no snapshots, the script will create one.
    After that it will proceed with backup/restore operation.

    It uses a second partition as target.

    Note: The script has to be run on the host. A second partition
    different from the Hyper-V one has to be available..
#>

param([string] $TestParams, [object] $AllVMData)
$ErrorActionPreference = "Stop"
#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    param (
        $TestParams, $AllVMData
    )
    $currentTestResult = Create-TestResultObject
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $VMIpv4 = $captureVMData.PublicIP
        $VMPort = $captureVMData.SSHPort
        $HypervGroupName=$captureVMData.HyperVGroupName
        Write-LogInfo "Test VM details :"
        Write-LogInfo "  RoleName : $($captureVMData.RoleName)"
        Write-LogInfo "  Public IP : $($captureVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($captureVMData.SSHPort)"
        Write-LogInfo "  HostName : $($captureVMData.HyperVhost)"
        $vmName1 = "${vmName}_ChildVM"
        Write-LogInfo "vmName1 Name is $vmName1"
        Set-Location $WorkingDirectory
        $sts = New-BackupSetup $VMName $HvServer
        if (-not $sts[-1]) {
            throw "Failed to create a backup setup"
        }
        # Check VSS Demon is running
        $sts = Check-VSSDemon $VMName $HvServer $VMIpv4 $VMPort
        if (-not $sts) {
            throw "VSS Daemon is not running"
        }
        # Create a file on the VM before backup
        $null = Run-LinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMPort -command "touch /home/$user/1" -runAsSudo
        if (-not $?) {
            throw "Cannot create test file"
        }
        $driveletter = $global:driveletter
        if ($null -eq $driveletter) {
            throw "driveletter not found"
        }
        # Stop the running VM so we can create New VM from this parent disk.
        # Shutdown gracefully so we dont corrupt VHD.
        Stop-VM -Name $VMName -ComputerName $HvServer
        if (-not $?) {
            throw "Unable to Shut Down VM"
        }
        # Add Check to make sure if the VM is shutdown then Proceed
        $timeout = 50
        $sts = Wait-ForVMToStop $VMName $HvServer $timeout
        if (-not $sts) {
            throw "Unable to Shut Down VM"
        }
        # Clean snapshots
        Write-LogInfo "INFO:  Cleaning up snapshots"
        $sts = Restore-LatestVMSnapshot $VMName $HvServer
        if (-not $sts[-1]) {
            throw "Cleaning snapshots on $VMName failed."
        }
        # Get Parent VHD
        $ParentVHD = Get-ParentVHD $VMName $HvServer
        if(-not $ParentVHD) {
            throw "Unable to get parent VHD of VM $VMName"
        }
        Write-LogInfo "Successfully Got Parent VHD"
        # Create Child and Grand-Child VHD, use temp path to avoid using same disk with backup drive
        $childVhd = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(),"vssVhd")
        $CreateVHD = Create-ChildVHD $ParentVHD $childVhd $HvServer
        if(-not $CreateVHD) {
            throw "Unable to create Child and Grand Child VHD of VM $VMName"
        }
        Write-LogInfo "Successfully created GrandChild VHD"
        # Now create New VM out of this VHD.
        # New VM is static hardcoded since we do not need it to be dynamic
        $GChildVHD = $CreateVHD
        # Get-VM
        $vm = Get-VM -Name $VMName -ComputerName $HvServer
        # Get the VM Network adapter so we can attach it to the new VM
        $VMNetAdapter = Get-VMNetworkAdapter $VMName
        if (-not $?) {
            throw "Unable to get network adapter"
        }
        #Get VM Generation
        $vm_gen = $vm.Generation
        # Create the GChildVM
        New-VM -Name $vmName1 -ComputerName $HvServer -VHDPath $GChildVHD -MemoryStartupBytes 1024MB -SwitchName $VMNetAdapter[0].SwitchName -Generation $vm_gen
        if (-not $?) {
            throw "Creating New VM"
        }
        # Disable secure boot
        if ($vm_gen -eq 2) {
            Set-VMFirmware -VMName $vmName1 -ComputerName $HvServer -EnableSecureBoot Off
            if(-not $?) {
                throw "Unable to disable secure boot"
            }
        }
        Write-LogInfo "New 3 Chain VHD VM $vmName1 created"
        $newIpv4 = Start-VMandGetIP $vmName1 $HvServer $VMPort $user $password
        Write-LogInfo "New VM $vmName1 started having IP $newIpv4"
        $sts = New-Backup $vmName1 $driveletter $HvServer $VMIpv4 $VMPort
        if (-not $sts[-1]) {
            throw "Failed to backup the VM"
        } else {
            $backupLocation = $sts[-1]
        }
        $sts = Restore-Backup $backupLocation $HypervGroupName $vmName1
        if (-not $sts[-1]) {
            throw "Restore backup action failed for $backupLocation"
        }
        $sts = Check-VMStateAndFileStatus $VMName $HvServer $VMIpv4 $VMPort
        if (-not $sts) {
            throw "Backup evaluation failed"
        }
        $sts = Stop-VM -Name $vmName1 -ComputerName $HvServer -TurnOff
        if (-not $?) {
            throw "Unable to Shut Down VM $vmName1"
        }
        $null = Remove-Backup $backupLocation
        if(-not $?) {
            throw "Cleanup is not properly done"
        }
        Write-LogInfo "Cleanup is completed"
        # Clean Delete New VM created
        $sts = Remove-VM -Name $vmName1 -ComputerName $HvServer -Confirm:$false -Force
        if (-not $?) {
            throw "Unable to delete New VM $vmName1"
        }
        Write-LogInfo "Deleted VM $vmName1"
        $testResult=$resultPass
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVMData $AllVMData
