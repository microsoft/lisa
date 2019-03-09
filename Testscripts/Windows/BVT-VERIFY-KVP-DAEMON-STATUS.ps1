# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData, [object] $CurrentTestData)

function Main {
    param([object] $allVMData, [object] $CurrentTestData)
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

        # REGION FOR CHECK KVP DAEMON STATUS
        Write-LogInfo "Executing : $($currentTestData.testScriptPs1)"
        Set-Content -Value "**************$($currentTestData.testName)******************" -Path "$logDir\$($currentTestData.testName)_Log.txt"
        Write-LogInfo "Verifcation of KVP Daemon status is started.."
        $kvpStatus = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "pgrep -lf 'hypervkvpd|hv_kvp_daemon'" -ignoreLinuxExitCode -RunAsSudo
        Add-Content -Value "KVP Daemon Status : $kvpStatus " -Path "$logDir\$($currentTestData.testName)_Log.txt"
        if ($kvpStatus -imatch "kvp") {
            Write-LogInfo "KVP daemon is present in remote VM and KVP DAEMON STATUS : $kvpStatus"
            $testResult = "PASS"
        } else {
            Write-LogInfo "KVP daemon is NOT present in remote VM and KVP DAEMON STATUS : $kvpStatus"
            $testResult = "FAIL"
        }
        Write-LogInfo "***********************KVP DAEMON STATUS ***********************"
        Write-LogInfo " KVP DAEMON STATUS: $kvpStatus"
        Write-LogInfo "******************************************************"
        Write-LogInfo "Test result : $testResult"
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -allVMData $AllVmData -CurrentTestData $CurrentTestData
