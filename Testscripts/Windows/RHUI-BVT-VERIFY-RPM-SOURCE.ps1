# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result 
    $result = ""
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        $DistroName = DetectLinuxDistro -VIP $AllVMData.PublicIP -SSHport $AllVMData.SSHPort -testVMUser $user -testVMPassword $password
        if ($DistroName.ToUpper() -eq "REDHAT") {
            RemoteCopy -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
            RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "chmod +x *" -runAsSudo
            LogMsg "Executing : $($currentTestData.testScript)"
            RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "bash $($currentTestData.testScript)" -runAsSudo -runMaxAllowedTime 1800
            RemoteCopy -download -downloadFrom $AllVMData.PublicIP -files "/home/$user/state.txt, /home/$user/Summary.log, /home/$user/$($currentTestData.testScript).log" -downloadTo $LogDir -port $AllVMData.SSHPort -username $user -password $password
            $testResult = Get-Content $LogDir\Summary.log
            $testStatus = Get-Content $LogDir\state.txt
            LogMsg "Test result : $testResult"
        } else {
            LogMsg "The Distro is not Redhat, skip the test!"
            $testResult = 'PASS'
            $testStatus = 'TestCompleted'
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
