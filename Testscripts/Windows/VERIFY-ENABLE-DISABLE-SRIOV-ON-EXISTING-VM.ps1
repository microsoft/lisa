# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData,
      [object] $CurrentTestData)

Function Run-CurrentTest ( [switch]$Enable, [switch]$Disable, [object]$CurrentTestResult, [object]$AllVmData) {
    if ($Enable) {
        $SRIOVChangeState = Set-SRIOVInVMs -AllVMData $AllVMData -Enable
        $ExpectedNics = 1
        $DesiredState = "Enable"
    }
    elseif ($Disable) {
        $SRIOVChangeState = Set-SRIOVInVMs -AllVMData $AllVMData -Disable
        $ExpectedNics = 0
        $DesiredState = "Disable"
    }
    if ($SRIOVChangeState) {
        $IsSriovVerified = Test-SRIOVInLinuxGuest -username "$user" -password $password `
            -IpAddress $AllVMData.PublicIP -SSHPort $AllVMData.SSHPort -ExpectedSriovNics $ExpectedNics
        if ( $IsSriovVerified ) {
            Write-LogInfo "$DesiredState Accelerated networking : verified successfully."
            $StageResult = $true
            $resultArr += "PASS"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "$DesiredState`SRIOV : Test Iteration - $TestIteration" `
                -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        }
        else {
            Write-LogInfo "$DesiredState Accelerated networking : Failed."
            $StageResult = $false
            $resultArr += "FAIL"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "$DesiredState`SRIOV : Test Iteration - $TestIteration" `
                -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            $FailureCount += 1
        }
    }
    else {
        Write-LogInfo "Test Accelerated networking : Failed."
        $resultArr += "FAIL"
        $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "$DesiredState`SRIOV : Test Iteration - $TestIteration" `
            -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        $FailureCount += 1
        $StageResult = $false
    }
    return $StageResult
}

function Main {
    param( [object]$AllVmData, [object]$CurrentTestData )
    $currentTestResult = Create-TestResultObject
    try {
        $resultArr = @()
        $Stage2Result = $true
        $FailureCount = 0
        #Enable SRIOV
        for ($TestIteration = 1 ; $TestIteration -le [int]$CurrentTestData.TestIterations; $TestIteration ++ ) {
            if ($Stage2Result) {
                Write-LogInfo "[Iteration : $TestIteration/$($CurrentTestData.TestIterations)] Stage 1: Enable SRIOV on Non-SRIOV Azure VM."
                $Stage1Result = $false
                $Stage1Result = Run-CurrentTest -Enable -CurrentTestResult $currentTestResult -AllVmData $AllVmData
            }
            else {
                #Break the for loop.
                $resultArr += "FAIL"
                $FailureCount += 1
                break;
            }

            if ($Stage1Result) {
                Write-LogInfo "[Iteration : $TestIteration/$($CurrentTestData.TestIterations)] Stage 2: Disable SRIOV on SRIOV Azure VM."
                $Stage2Result = $false
                $Stage2Result = Run-CurrentTest -Disable -CurrentTestResult $currentTestResult -AllVmData $AllVmData
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

        Write-LogInfo "Test Completed."
        Write-LogInfo "Test Result: $testResult"

    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    Finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData
