# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests VSS backup functionality.
.Description
    This script will set the vm in Paused, Saved or Off state.
    After that it will perform backup/restore.

    It uses a second partition as target.

    Note: The script has to be run on the host. A second partition
          different from the Hyper-V one has to be available.

#>
param([string] $TestParams, [object] $AllVMData)

$ErrorActionPreference = "Stop"

#######################################################################
# Channge the VM state
#######################################################################
function Change-VMState($vmState,$vmName,$hvServer)
{
    $vm = Get-VM -Name $vmName -ComputerName $hvServer
    if ($vmState -eq "Off") {
        Stop-VM -Name $vmName -ComputerName $hvServer -ErrorAction SilentlyContinue
        return $vm.state
    }
    elseif ($vmState -eq "Saved") {
        Save-VM -Name $vmName -ComputerName $hvServer -ErrorAction SilentlyContinue
        return $vm.state
    }
    elseif ($vmState -eq "Paused") {
        Suspend-VM -Name $vmName -ComputerName $hvServer -ErrorAction SilentlyContinue
        return $vm.state
    }
    else {
        return $false
    }
}
#######################################################################
#
# Main script body
#
#######################################################################
function Main
{
    param (
        $TestParams, $AllVMData
    )
    $currentTestResult = Create-TestResultObject
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $VMIpv4=$captureVMData.PublicIP
        $VMPort=$captureVMData.SSHPort
        $vmState=$TestParams.vmState
        $HypervGroupName=$captureVMData.HyperVGroupName
        Write-LogInfo "Test VM details :"
        Write-LogInfo "  RoleName : $($captureVMData.RoleName)"
        Write-LogInfo "  Public IP : $($captureVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($captureVMData.SSHPort)"
        Write-LogInfo "  HostName : $($captureVMData.HyperVhost)"
        Write-LogInfo "vmstate from params  is $vmState"
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        Write-LogInfo "WorkingDirectory"
        $sts = New-BackupSetup $VMName $HvServer
        if (-not $sts[-1]) {
            throw "Failed to create a Backup Setup"
        }
        # Check VSS Demon is running
        $sts = Check-VSSDemon $VMName $HvServer $VMIpv4 $VMPort
        if (-not $sts) {
            throw "VSS Daemon is not running"
        }
        # Create a file on the VM before backup
        Run-LinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMPort -command "touch /home/$user/1" -runAsSudo
        if (-not $?) {
            throw "Cannot create test file"
        }
        $driveletter = $global:driveletter
        if ($null -eq $driveletter) {
            Write-LogErr "Backup driveletter is not specified."
        }
        Write-LogInfo "Driveletter is $driveletter"
        # Check if VM is Started
        $vm = Get-VM -Name $VMName
        $currentState=$vm.state
        Write-LogInfo "current vm state is $currentState "
        if ( $currentState -ne "Running" ) {
            Write-LogErr "$vmName is not started."
        }
        # Change the VM state
        $sts = Change-VMState $vmState $VMName $HvServer
        Write-LogInfo "VM state changed to $vmstate :  $sts"
        if (-not $sts[-1]) {
            throw "vmState param: $vmState is wrong. Available options are `'Off`', `'Saved`'' and `'Paused`'."
        }
        elseif ( $sts -ne $vmState ) {
            throw "Failed to put $vmName in $vmState state $sts."
        }
        Write-LogInfo "State change of $vmName to $vmState : Success."
        $sts = New-Backup $VMName $driveletter $HvServer $VMIpv4 $VMPort
        if (-not $sts[-1]) {
            throw "Could not create a Backup Location"
        } else {
            $backupLocation = $sts[-1]
        }
        $sts = Restore-Backup $backupLocation $HypervGroupName $VMName
        if (-not $sts[-1]) {
            throw "Restore backup action failed for $backupLocation"
        }
        $sts = Check-VMStateAndFileStatus $VMName $HvServer $VMIpv4 $VMPort
        if (-not $sts[-1]) {
            throw "Backup evaluation failed"
        }
        Remove-Backup $backupLocation | Out-Null
        if( $testResult -ne $resultFail) {
            $testResult=$resultPass
        }
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main -TestParams  (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVMData $AllVMData

