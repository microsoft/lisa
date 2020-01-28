# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests VSS backup functionality.
.Description
    This script will backup vm when vm has read-only file which
    is created by mksquashfs.
#>
param([object] $AllVMData)

$ErrorActionPreference = "Stop"
function Main {
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer = $captureVMData.HyperVhost
        $VMIpv4 = $captureVMData.PublicIP
        $VMPort = $captureVMData.SSHPort
        $HypervGroupName = $captureVMData.HyperVGroupName
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        $sts = New-BackupSetup $VMName $HvServer
        if (-not $sts[-1]) {
            throw "Failed to create a Backup setup"
        }
        $sts = Check-VSSDemon $VMName $HvServer $VMIpv4 $VMPort
        # Check VSS Demon is running
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
            $testResult = $resultFail
            throw "Backup driveletter is not specified."
        }
        $remoteScript = "STOR_VSS_Disk_Mount_Squashfs.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $VMIpv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
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
        if (-not $sts) {
            throw "Backup evaluation failed"
        }
        Remove-Backup $backupLocation | Out-Null
        if( $testResult -ne $resultFail) {
            $testResult=$resultPass
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main
