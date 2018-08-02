# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result 
    $result = ""
    $currentTestResult = CreateTestResultObject
    $resultArr = @()
    
    try {  
        ProvisionVMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

        # REGION FOR CHECK KVP DAEMON STATUS
        LogMsg "Executing : $($currentTestData.testScriptPs1)"
        Set-Content -Value "**************$($currentTestData.testName)******************" -Path "$logDir\$($currentTestData.testName)_Log.txt"
        LogMsg "Verifcation of KVP Daemon status is started.."
        $kvpStatus = RunLinuxCmd -username "root" -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "pgrep -lf 'hypervkvpd|hv_kvp_daemon'" 
        Add-Content -Value "KVP Daemon Status : $kvpStatus " -Path "$logDir\$($currentTestData.testName)_Log.txt"
        if ($kvpStatus -imatch "kvp") {
            LogMsg "KVP daemon is present in remote VM and KVP DAEMON STATUS : $kvpStatus"
            $testResult = "PASS"
        } else {
            LogMsg "KVP daemon is NOT present in remote VM and KVP DAEMON STATUS : $kvpStatus"
            $testResult = "FAIL"
        }
        LogMsg "***********************KVP DAEMON STATUS ***********************"
        LogMsg " KVP DAEMON STATUS: $kvpStatus" 
        LogMsg "******************************************************"
        LogMsg "Test result : $testResult"
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogMsg "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        $metaData = ""
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult  
    }   

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
