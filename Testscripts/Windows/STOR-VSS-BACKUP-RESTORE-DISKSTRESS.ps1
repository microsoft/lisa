# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests VSS backup functionality.
.Description
    This script will push VSS_Disk_Stress.sh script to the vm.
    While the script is running it will perform the backup/restore operation.
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
        $HypervGroupName=$captureVMData.HyperVGroupName
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
            $testResult = $resultFail
            throw "Backup driveletter is not specified."
        }
        $remoteScript="STOR_VSS_Disk_Stress.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        # Wait 5 seconds for stress action to start on the VM
        Start-Sleep -s 5
        $sts = New-Backup $VMName $BackupDriveLetter $HvServer $Ipv4 $VMPort
        if (-not $sts[-1]) {
            throw "Could not retrieve Backup Location"
        }
        else {
            $backupLocation = $sts[-1]
        }
        $sts = Restore-Backup $backupLocation $HypervGroupName $VMName
        if (-not $sts[-1]) {
            throw "Restore backup action failed"
        }
        $sts = Check-VMStateAndFileStatus $VMName $HvServer $Ipv4 $VMPort
        if (-not $sts) {
            throw "Backup evaluation failed"
        }
        $null = Remove-Backup $backupLocation
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
