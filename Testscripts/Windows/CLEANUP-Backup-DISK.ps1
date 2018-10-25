# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script creates a disk to be used for backup and restore tests
.Description
    This script will create a new VHD double the size of the VHD in the
    given vm. The VHD will be mounted to a new partiton, initialized and
    formatted with NTFS
#>
$ErrorActionPreference = "Stop"
function Main {
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        $backupdiskpath = (Get-VMHost).VirtualHardDiskPath + "\" + $VMName + "_VSS_DISK.vhdx"
        $tempFile = (Get-VMHost).VirtualHardDiskPath + "\" + $VMName + "_DRIVE_LETTER.txt"
        # This is used to set the $global:driveletter variable
        Get-DriveLetter $VMName $HvServer
        if ($global:driveletter) {
            Dismount-VHD -Path $backupDiskPath -ErrorAction SilentlyContinue
            if (-not $?) {
                LogErr "Dismounting VHD has failed"
            }
            Remove-Item $backupdiskpath -Force -ErrorAction SilentlyContinue
            if (-not $?) {
                LogErr "Could not remove backup disk"
            }
            Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
            if (-not $?) {
                LogErr "Could not remove temporary file"
            }
            LogMsg "Cleanup completed!"
            $testResult=$resultPass
        }
        else {
            LogErr "Drive letter isn't set"
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main
