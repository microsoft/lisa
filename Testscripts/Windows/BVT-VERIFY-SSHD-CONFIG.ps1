# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result 
    $result = ""
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        $testScript = "BVT-VERIFY-SSHD-CONFIG.py"

        RemoteCopy -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
        RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "chmod +x *" -runAsSudo
        
        LogMsg "Executing : ${testScript}"
        $output=RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "$python_cmd ${testScript}" -runAsSudo
        RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "mv Runtime.log ${testScript}.log" -runAsSudo
        RemoteCopy -download -downloadFrom $AllVMData.PublicIP -files "/home/$user/state.txt, /home/$user/Summary.log, /home/$user/${testScript}.log" -downloadTo $LogDir -port $AllVMData.SSHPort -username $user -password $password
        $testResult = Get-Content $LogDir\Summary.log
        $testStatus = Get-Content $LogDir\state.txt
        LogMsg "Test result : $testResult"

        if ($output -imatch "CLIENT_ALIVE_INTERVAL_SUCCESS") {
            LogMsg "SSHD-CONFIG INFO :Client_Alive_Interval time is 180 Second"
        } else {
            if ($output -imatch "CLIENT_ALIVE_INTERVAL_FAIL") {
                LogMsg "SSHD-CONFIG INFO :There is no Client_Alive_Interval time is 180 Second"
            }
            if ($output -imatch "CLIENT_ALIVE_INTERVAL_COMMENTED") {
                LogMsg "SSHD-CONFIG INFO :There is a commented line in CLIENT_INTERVAL_COMMENTED "
            }
        }
        
        if ($testStatus -eq "TestCompleted") {
            LogMsg "Test Completed"
        }
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
