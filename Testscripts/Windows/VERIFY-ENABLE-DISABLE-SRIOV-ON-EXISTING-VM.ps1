# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
Function Run-CurrentTest ( [switch]$Enable, [switch]$Disable) {
    if ($Enable) {
        $SRIOVChangeState = Set-SRIOVInVMs -VirtualMachinesGroupName $AllVMData.ResourceGroupName -Enable
        $ExpectedNics = 1
        $DesiredState = "Enable"
    }
    elseif ($Disable) {
        $SRIOVChangeState = Set-SRIOVInVMs -VirtualMachinesGroupName $AllVMData.ResourceGroupName -Disable
        $ExpectedNics = 0
        $DesiredState = "Disable"
    }
    if ($SRIOVChangeState) {
        $IsSriovVerified = Test-SRIOVInLinuxGuest -username "root" -password $password `
            -IpAddress $AllVMData.PublicIP -SSHPort $AllVMData.SSHPort -ExpectedSriovNics $ExpectedNics
        if ( $IsSriovVerified ) {
            LogMsg "$DesiredState Accelerated networking : verified successfully."
            $StageResult = $true
            $resultArr += "PASS"
            $CurrentTestResult.TestSummary += CreateResultSummary -testResult "PASS" -metaData "$DesiredState`SRIOV : Test Iteration - $TestIteration" `
                -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        }
        else {
            LogMsg "$DesiredState Accelerated networking : Failed."
            $StageResult = $false
            $resultArr += "FAIL"
            $CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "$DesiredState`SRIOV : Test Iteration - $TestIteration" `
                -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            $FailureCount += 1
        }
    }
    else {
        LogMsg "Test Accelerated networking : Failed."
        $resultArr += "FAIL"
        $CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "$DesiredState`SRIOV : Test Iteration - $TestIteration" `
            -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        $FailureCount += 1
        $StageResult = $false
    }
    return $StageResult
}

function Main {
    try {
        $resultArr = @()
        $Stage2Result = $true
        $FailureCount = 0
        #Enable SRIOV
        for ($TestIteration = 1 ; $TestIteration -le [int]$CurrentTestData.TestIterations; $TestIteration ++ ) {
            if ($Stage2Result) {
                LogMsg "[Iteration : $TestIteration/$($CurrentTestData.TestIterations)] Stage 1: Enable SRIOV on Non-SRIOV Azure VM."
                $Stage1Result = $false
                $Stage1Result = Run-CurrentTest -Enable
            }
            else {
                #Break the for loop.
                $resultArr += "FAIL"
                $FailureCount += 1
                break;
            }

            if ($Stage1Result) {
                LogMsg "[Iteration : $TestIteration/$($CurrentTestData.TestIterations)] Stage 2: Disable SRIOV on SRIOV Azure VM."
                $Stage2Result = $false
                $Stage2Result = Run-CurrentTest -Disable
            }
            else {
                #Break the for loop.
                $resultArr += "FAIL"
                $FailureCount += 1
                break;
            }
        }

        if ($FailureCount -eq 0) {
            $testResult = "PASS"
        }
        else {
            $testResult = "FAIL"
        }

        LogMsg "Test Completed."
        LogMsg "Test Result: $testResult"

    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    Finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
