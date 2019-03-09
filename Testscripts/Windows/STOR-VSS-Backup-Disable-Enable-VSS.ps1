# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests VSS backup functionality.
.Description
    This script will set Integration Services "Backup (volume checkpoint)" -VSS as disabled,
    then do offline backup, set VSS as enabled, then do online backup.
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
        # set the backup type array, if set Integration Service VSS
        # as disabled/unchecked, it executes offline backup, if VSS is
        # enabled/checked and hypervvssd is running, it executes online backup.
        $backupTypes = @("offline","online")
        # checkVSSD uses to set integration service,
        # also uses to define whether need to check
        # hypervvssd running status during runSetup
        $checkVSSD= @($false,$true)
        # If the kernel version is smaller than 3.10.0-383,
        # it does not take effect after un-check then
        # check VSS service unless restart VM.
        $supportkernel = "3.10.0.383"
        $supportStatus = Get-VMFeatureSupportStatus $Ipv4 $VMPort $user $password $supportkernel
        for ($i = 0; $i -le 1; $i++ ) {
            # stop vm then set integration service
            if (-not $supportStatus[-1]) {
                # need to stop-vm to set integration service
                Stop-VM -Name $VMName -ComputerName $HvServer -Force
            }
            # set service status based on checkVSSD
            $sts = Set-IntegrationService $VMName $HvServer "VSS" $checkVSSD[$i]
            if (-not $sts[-1]) {
                throw "${VMName} failed to set Integration Service"
            }
            Write-LogInfo "Set-IntegrationServic has been set"
            #  Restart the VM to make VSS service change take effect
            if (-not $supportStatus[-1]) {
                $timeout = 300
                $sts = Start-VM -Name $VMName -ComputerName $HvServer
                if (-not (Wait-ForVMToStartKVP $VMName $HvServer $timeout )) {
                    throw "${VMName} failed to start"
                }
                Start-Sleep -s 3
            }
            $sts = New-BackupSetup $VMName $HvServer
            if (-not $sts[-1]) {
                throw "Run setup failed"
            }
            if($checkVSSD[$i]) {
                # Check VSS Demon is running
                $sts = Check-VSSDemon $VMName $HvServer $Ipv4 $VMPort
                if (-not $sts){
                    throw "VSS Daemon is not running"
                }
            }
            # Create a file on the VM before backup
            $null = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch /home/$user/1" -runAsSudo
            $BackupDriveLetter = $global:driveletter
            if ($null -eq $BackupDriveLetter) {
                throw "Backup driveletter is not specified."
            }
            $sts = New-Backup $VMName $BackupDriveLetter $HvServer $Ipv4 $VMPort
            if (-not $sts[-1]) {
                throw "Failed in start Backup"
            }
            else {
                $backupLocation = $sts[-1]
            }
            # check the backup type, if VSS integration service is disabled,
            # it executes offline backup, otherwise, it executes online backup.
            $sts = Get-BackupType
            $temp = $backupTypes[$i]
            if  ( $sts -ne $temp ) {
                $testResult = $resultFail
                throw "Didn't get expected backup type"
            }
            else {
                Write-LogInfo "Received expected backup type $temp"
            }
            $null = Remove-Backup $backupLocation
        }
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
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main
