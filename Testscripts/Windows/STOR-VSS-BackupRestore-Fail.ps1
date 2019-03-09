# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests VSS backup functionality.

.Description
    This script will push test if VSS backup will gracefully fail in case
    of failure.
    It uses a second partition as target.
#>
param([object] $AllVMData)

$ErrorActionPreference = "Stop"
function Main {
    $currentTestResult = Create-TestResultObject
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4=$captureVMData.PublicIP
        $VMPort=$captureVMData.SSHPort
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        $sts = New-BackupSetup $VMName $HvServer
        if (-not $sts[-1]) {
            throw "Run setup failed"
        }
        # Check VSS Demon is running
        $sts = Check-VSSDemon $VMName $HvServer $Ipv4 $VMPort
        if (-not $sts){
            throw "VSS Daemon is not running"
        }
        # Create a file on the VM before backup
        $null = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch /home/$user/1" -runAsSudo
        $BackupDriveLetter = $global:driveletter
        if ($null -eq $BackupDriveLetter) {
            throw "Test parameter BackupDriveLetter was not specified."
        }
        # Run the remote script
        $remoteScript = "STOR_VSS_Disk_Fail.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        $sts = New-Backup $VMName $BackupDriveLetter $HvServer $Ipv4 $VMPort
        if (-not $sts[-1]) {
            throw "Could not retrieve Backup Location"
        }
        else {
            $backupLocation = $sts[-1]
        }
        Write-LogInfo "Going through event logs for Warning ID 10107"
        # Now Check if Warning related Error is present in Event Log ? Backup should fail .
        $EventLog = Get-WinEvent -ProviderName Microsoft-Windows-Hyper-V-VMMS | Where-Object {  $_.TimeCreated -gt $Date}
        if(-not $EventLog) {
            throw "Cannot get Event log."
        }
        # Event ID 10107 is what we looking here, it will be always be 10107.
        foreach ($event in $EventLog) {
            Write-LogInfo "VSS Backup Error in Event Log number is $($event.ID)"
            if ($event.Id -eq 10150) {
                $found_eventid = $True
                Write-LogInfo $event.Message
                Write-LogInfo "VSS Backup Error in Event Log : Success"
            }
        }
        if (-not $found_eventid) {
            Write-LogWarn "VSS Backup Error not in Event Log"
        }
        $null = Remove-Backup $backupLocation
        if( $testResult -ne $resultFail) {
            $testResult=$resultPass
        }
    }
    catch {
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
