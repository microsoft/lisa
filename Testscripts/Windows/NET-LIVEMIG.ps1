# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Performs basic Live/Quick Migration operations
.Description
    This is a Powershell test case script that implements Live/Quick Migration
    of a VM.
    Keeps pinging the VM while migration is in progress, ensures that migration
    of VM is successful and the that the ping should not loose
#>
param([String] $TestParams)
$ErrorActionPreference = "Stop"
$stopClusterNode= $False
$VMMemory = $null
function Main {
    param (
        $TestParams
    )
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort
        $MigrationType= $TestParams.MigrationType
        if($TestParams.stopClusterNode) {
            $StopClusterNode = $TestParams.stopClusterNode
        }
        if($TestParams.VMMemory) {
            $VMMemory= $TestParams.VMMemory
        }
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        LogMsg "Trying to ping the VM before starting migration"
        $timeout = 600
        while ($timeout -gt 0) {
            if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
                break
            }
            Start-Sleep -seconds 2
            $timeout -= 2
        }
        if ($timeout -eq 0) {
            throw "Test case timed out waiting for VM to boot"
        }
        LogMsg "Starting migration job"
        $job = Start-Job -FilePath "$WorkingDirectory\Testscripts\Windows\Migrate-VM.ps1" -ArgumentList $VMName,$HvServer,$MigrationType,$StopClusterNode,$VMMemory,$WorkingDirectory
        if (-not $job) {
            throw "Migration job not started"
        }
        LogMsg "Checking if the migration job is actually running"
        $jobInfo = Get-Job -Id $job.Id
        if($jobInfo.State -ne "Running") {
            throw "Migration job did not start or terminated immediately"
        }
        LogMsg "Test TCP port during the migration"
        $migrateJobRunning = $true
        while ($migrateJobRunning) {
            $timeout = 600
            while ($timeout -gt 0) {
                if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
                    break
                }
                Start-Sleep -seconds 2
                $timeout -= 2
            }
            if ($timeout -eq 0) {
                throw "Test case timed out waiting for VM to boot"
            }
            # Copying file during migration
            if($TestParams.CopyFile) {
                LogMsg "Creating a 256MB temp file"
                $random = Get-Random -minimum 1024 -maximum 4096
                $filesize=256MB
                $testfile = "TestFile_$random"
                $createfile = fsutil file createnew $WorkingDirectory\$testfile $filesize
                if ($createfile -notlike "File *TestFile_* is created") {
                    throw "Could not create $testfile in the working directory!"
                }
                LogMsg "Copying temp file to VM"
                RemoteCopy -upload -uploadTo $Ipv4 -Port $VMPort `
                    -files $testfile -Username $user -password $password
                $TestParams.CopyFile = $False
            }
            $jobInfo = Get-Job -Id $job.Id
            if($jobInfo.State -eq "Completed") {
                $migrateJobRunning = $False
            }
            if($jobInfo.State -eq "Failed") {
                $migrateJobRunning = $False
                throw "Job Failed"
            }
        }
        $timeout = 600
        while ($timeout -gt 0) {
            if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
                break
            }
            Start-Sleep -seconds 2
            $timeout -= 2
        }
        if ($timeout -eq 0) {
            throw "Test case timed out waiting for VM to boot"
        }
        if( $testResult -ne $resultFail) {
            $testResult=$resultPass
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
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
