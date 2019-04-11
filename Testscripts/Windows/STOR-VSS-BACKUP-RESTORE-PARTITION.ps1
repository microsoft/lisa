# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests VSS backup functionality.
.Description
    This script will format and mount connected disk in the VM.
    After that it will proceed with backup/restore operation.
    It uses a second partition as target.
#>
param([string] $TestParams, [object] $AllVMData)

$ErrorActionPreference = "Stop"
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
        if (-not $?) {
            throw "Cannot create test file"
        }
        # Check SecureBoot is enabled
        if ( $TestParams.secureBootVM ) {
            # Check if Secure boot settings are in place before the backup
            $firmwareSettings = Get-VMFirmware -VMName $VMName
            if ($firmwareSettings.SecureBoot -ne "On") {
                $testResult = $resultFail
                throw "Secure boot settings changed"
            }
        }
        $driveletter = $global:driveletter
        if ($null -eq $driveletter) {
            $testResult = $resultFail
            throw "Backup driveletter is not specified."
        }
        # Run the Partition Disk script
        if (-not $TestParams.secureBootVM) {
            $remoteScript="PartitionMultipleDisks.sh"
            $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
            if ($retval -eq $False) {
                throw "Running $remoteScript script failed on VM!"
            }
        }
        $sts = New-Backup $VMName $driveletter $HvServer $Ipv4 $VMPort
        if (-not $sts[-1]) {
            throw "Could not create a Backup Location"
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
        if ( $TestParams.secureBootVM ) {
            # Check if Secure boot settings are in place before the backup
            $firmwareSettings = Get-VMFirmware -VMName $VMName
            if ($firmwareSettings.SecureBoot -ne "On") {
                $testResult = $resultFail
                throw "Secure boot settings changed after restoring backup"
            }
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
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVMData $AllVMData
