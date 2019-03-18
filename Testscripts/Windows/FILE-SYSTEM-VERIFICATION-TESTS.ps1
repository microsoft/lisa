# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#     This Powershell script will run xfstesting.sh bash script
#     - It will construct the config file needed by xfstesting.sh
#     - It will start xfstesting.sh. Max allowed run time is 3 hours.
#     - If state.txt is in TestRunning state after 3 hours, it will
#     abort the test.
#######################################################################
param([object] $AllVmData,
      [object] $CurrentTestData
    )

function Main {
    param (
        $AllVmData,
        $CurrentTestData
    )
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    $superuser = "root"

    try {
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort `
            -files $currentTestData.files -username $superuser -password $password -upload

        # Construct xfstesting config file
        $xfstestsConfig = Join-Path $env:TEMP "xfstests-config.config"
        Write-LogInfo "Generating $xfstestsConfig..."
        Set-Content -Value "" -Path $xfstestsConfig -NoNewline
        foreach ($param in $currentTestData.TestParameters.param) {
            if ($param -imatch "FSTYP=") {
                $TestFileSystem = ($param.Replace("FSTYP=",""))
                Add-Content -Value "[$TestFileSystem]" -Path $xfstestsConfig
                Write-LogInfo "[$TestFileSystem] added to xfstests-config.config"
            }
            Add-Content -Value "$param" -Path $xfstestsConfig
            Write-LogInfo "$param added to xfstests-config.config"
        }
        Write-LogInfo "$xfstestsConfig created successfully"

        # Start the test script
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort `
            -files $xfstestsConfig -username $superuser -password $password -upload
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
            -password $password -command "/$superuser/xfstesting.sh" -RunInBackground | Out-Null
        # Check the status of the run every minute
        # If the run is longer than 3 hours, abort the test
        $timeout = New-Timespan -Minutes 180
        $sw = [diagnostics.stopwatch]::StartNew()
        while ($sw.elapsed -lt $timeout) {
            Start-Sleep -s 60
            $state = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
                -username $superuser -password $password "cat state.txt"
            if ($state -eq "TestCompleted") {
                Write-LogInfo "xfstesting.sh finished the run successfully!"
                break
            } elseif ($state -eq "TestFailed") {
                Write-LogErr "xfstesting.sh failed on the VM!"
                break
            }
            Write-LogInfo "xfstesting.sh is still running!"
        }

        # Get logs. An extra check for the previous $state is needed
        # The test could actually hang. If state.txt is showing
        # 'TestRunning' then abort the test
        #####
        # We first need to move copy from root folder to user folder for
        # Collect-TestLogs function to work
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
            -password $password -command "cp * /home/$user" -ignoreLinuxExitCode:$true | Out-Null
        $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName `
            $currentTestData.files.Split('\')[3].Split('.')[0] -TestType "sh"  -PublicIP `
            $allVMData.PublicIP -SSHPort $allVMData.SSHPort -Username $user `
            -password $password -TestName $currentTestData.testName
        if ($state -eq "TestRunning") {
            $resultArr += "ABORTED"
            Write-LogErr "xfstesting.sh is still running after 4 hours!"
        } else {
            $resultArr += $testResult
        }

        Write-LogInfo "Test Completed."
        Write-LogInfo "Test Result: $testResult"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION: $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData