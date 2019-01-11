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
param([String] $TestParams,
      [object] $AllVmData)

$ErrorActionPreference = "Stop"
$stopClusterNode= $False
$VMMemory = $null
function Main {
    param (
        $TestParams,
        $AllVmData
    )
    $currentTestResult = Create-TestResultObject
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
        Write-LogInfo "Trying to ping the VM before starting migration"
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
        Write-LogInfo "Starting migration job"
        $job = Start-Job -FilePath "$WorkingDirectory\Testscripts\Windows\Migrate-VM.ps1" -ArgumentList $VMName,$HvServer,$MigrationType,$StopClusterNode,$VMMemory,$WorkingDirectory
        if (-not $job) {
            throw "Migration job not started"
        }
        Write-LogInfo "Checking if the migration job is actually running"
        $jobInfo = Get-Job -Id $job.Id
        if($jobInfo.State -ne "Running") {
            throw "Migration job did not start or terminated immediately"
        }
        Write-LogInfo "Test TCP port during the migration"
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
                Write-LogInfo "Creating a 256MB temp file"
                $random = Get-Random -minimum 1024 -maximum 4096
                $filesize=256MB
                $testfile = "TestFile_$random"
                $createfile = fsutil file createnew $WorkingDirectory\$testfile $filesize
                if ($createfile -notlike "File *TestFile_* is created") {
                    throw "Could not create $testfile in the working directory!"
                }
                Write-LogInfo "Copying temp file to VM"
                Copy-RemoteFiles -upload -uploadTo $Ipv4 -Port $VMPort `
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
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVmData $AllVmData
