# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests VSS backup functionality.
.Description
    This script will stop hypervvssd daemons then do offline backup, then start hypervvssd again to do online backup.
.Parameter vmName
    Name of the VM to backup
.Parameter hvServer
    Name of the Hyper-V server hosting the VM.
.Parameter testParams
    Test data for this test case
#>

param([object] $AllVMData)
$remoteScript = "STOR_VSS_Set_VSS_Daemon.sh"

#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    $currentTestResult = Create-TestResultObject
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $VMIpv4 = $captureVMData.PublicIP
        $VMPort = $captureVMData.SSHPort
        #region CONFIGURE VM FOR N SERIES GPU TEST
        Write-LogInfo "Test VM details :"
        Write-LogInfo "  RoleName : $($captureVMData.RoleName)"
        Write-LogInfo "  Public IP : $($captureVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($captureVMData.SSHPort)"
        Write-LogInfo "  HostName : $($captureVMData.HyperVhost)"
        # Change the working directory to where we need to be
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
            throw "Backup driveletter is not specified."
        }
        # set the backup type array, if stop hypervvssd, it executes offline backup, if start hypervvssd, it executes online backup
        $backupTypes = @("offline","online")
        # set hypervvssd status, firstly stop, then start
        $setAction= @("stop","start")
        for ($i = 0; $i -le 1; $i++ ) {
            $serviceAction = $setAction[$i]
            $serviceCommand = "echo serviceAction=$serviceAction  >> constants.sh"
            $null = Run-LinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMPort $serviceCommand -runAsSudo
            if (-not $sts[-1]) {
                throw "Could not echo serviceAction to vm's constants.sh."
            }
            Write-LogInfo "$serviceAction hyperv backup service"
            # Run the remote script
            $sts = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $VMIpv4 $VMPort
            if (-not $sts[-1]) {
                throw "Running $remoteScript script failed on VM!"
            }
            Start-Sleep -s 3
            $stsBackUp = New-Backup $VMName $driveLetter $HvServer $VMIpv4 $VMPort
            # when stop hypervvssd, backup offline backup
            if ( -not $stsBackUp[-1]) {
                throw "Failed in start Backup"
            }
            else {
                $backupLocation = $stsBackUp
                # if stop hypervvssd, vm does offline backup
                $bkType = Get-BackupType
                $temp = $backupTypes[$i]
                if ( $bkType -ne $temp ) {
                    $testResult = "FAIL"
                    throw "Failed: Not get expected backup type as $temp"
                }
                else {
                     Write-LogInfo "Got expected backup type $temp"
                }
              $null = Remove-Backup $backupLocation
            }
        }
        $testResult = "PASS"
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
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
Main
