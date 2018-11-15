# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script creates a disk to be used for backup and restore tests
.Description
    This scrip will create a new VHD double the size of the VHD in the
    given vm. The VHD will be mounted to a new partiton, initialized and
    formatted with NTFS
#>
$ErrorActionPreference = "Stop"
function Main {
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        $backupdisksize = 2*$(Get-VMHardDiskDrive -VMName $VMName |get-vhd)[0].size
        $backupdiskpath = (Get-VMHost).VirtualHardDiskPath + "\" + $VMName + "_VSS_DISK.vhdx"
        $driveletter = Get-ChildItem function:[g-y]: -n | Where-Object { !(test-path $_) } | Get-random
        $originaldriveletter = $driveletter
        [char]$driveletter = $driveletter.Replace(":","")
        if ([string]::IsNullOrEmpty($driveletter)) {
            throw "Setup: The driveletter variable is empty!"
        }
        $maxRetryCount=2
        $currentRetryCount = 0
        while ($currentRetryCount -lt $maxRetryCount){
            if (Test-Path ($backupdiskpath)) {
                LogMsg "Disk already exists. Deleting old disk and creating new disk."
                Dismount-VHD $backupdiskpath
                Remove-Item $backupdiskpath
            }
            New-VHD -Path $backupdiskpath -Size $backupdisksize
            Mount-VHD -Path $backupdiskpath
            if($?) {
                break
            }
            $currentRetryCount++
        }
        if ($currentRetryCount -eq $maxRetryCount) {
            throw "Mounting VHD Failed"
        }
        $backupdisk = Get-VHD -Path $backupdiskpath
        Initialize-Disk $backupdisk.DiskNumber
        $diskpartition = New-Partition -DriveLetter $driveletter -DiskNumber $backupdisk.DiskNumber -UseMaximumSize
        $volume = Format-Volume -FileSystem NTFS -Confirm:$False -Force -Partition $diskpartition
        LogMsg "Disk initialized with volume $volume $diskpartition"
        New-PSDrive -Name $driveletter -PSProvider FileSystem -Root $originaldriveletter -Description "VSS"
        $filePath = (Get-VMHost).VirtualHardDiskPath + "\" + "$VMName" + "_DRIVE_LETTER.txt"
        if(Test-Path ($filePath)) {
            LogMsg "Removing existing file."
            Remove-Item $filePath
        }
        Write-Output "$originaldriveletter" >> $filePath
        $testResult=$resultPass
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
