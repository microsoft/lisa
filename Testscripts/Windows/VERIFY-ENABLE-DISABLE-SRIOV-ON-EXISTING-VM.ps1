# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    try {
        $resultArr = @()
        $Stage2Result = $true
        $SuperUser = "root"
        #Enable SRIOV
        for ($TestIteration = 1 ; $TestIteration -le [int]$CurrentTestData.TestIterations; $TestIteration ++ ) {
            if ($Stage2Result) {
                LogMsg "[Iteration : $TestIteration/$($CurrentTestData.TestIterations)] Stage 1: Enable SRIOV on Non-SRIOV Azure VM."
                $IsSriovEnabled = Enable-SRIOVinAzureVM -ResourceGroup $AllVMData.ResourceGroupName -VMName $AllVMData.RoleName
                if ($IsSriovEnabled) {
                    $IsSriovVerified = Test-SRIOVInLinuxGuest -username $SuperUser -password $password `
                    -IpAddress $AllVMData.PublicIP -SSHPort $AllVMData.SSHPort -ExpectedSriovNics 1
                    if ( $IsSriovVerified ) {
                        LogMsg "Enable Accelerated networking : verified successfully."
                        $Stage1Result = $true
                        $resultArr += "PASS"
                        $CurrentTestResult.TestSummary += CreateResultSummary -testResult "PASS" -metaData "EnableSRIOV : Test Iteration - $TestIteration" `
                        -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    }
                    else {
                        LogMsg "Enable Accelerated networking : Failed."
                        $Stage1Result = $false
                        $resultArr += "FAIL"
                        $CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "EnableSRIOV : Test Iteration - $TestIteration" `
                        -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    }
                } else {
                    LogMsg "Test Accelerated networking : Failed."
                    $Stage1Result = $false
                    $resultArr += "FAIL"
                    $CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "EnableSRIOV : Test Iteration - $TestIteration" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName                    
                }
            }
            else {
                #Break the for loop.
                $resultArr += "FAIL"
                break;
            }

            if ($Stage1Result) {
                LogMsg "[Iteration : $TestIteration/$($CurrentTestData.TestIterations)] Stage 2: Disable SRIOV on SRIOV Azure VM."
                $Stage2Result = $false
                $IsSriovDisabled = Disable-SRIOVinAzureVM -ResourceGroup $AllVMData.ResourceGroupName -VMName $AllVMData.RoleName
                if ($IsSriovDisabled) {
                    $IsSriovVerified = Test-SRIOVInLinuxGuest -username $SuperUser -password $password `
                    -IpAddress $AllVMData.PublicIP -SSHPort $AllVMData.SSHPort -ExpectedSriovNics 0
                    if ( $IsSriovVerified ) {
                        LogMsg "Disable Accelerated networking : verified successfully."
                        $Stage2Result = $true
                        $resultArr += "PASS"
                        $CurrentTestResult.TestSummary += CreateResultSummary -testResult "PASS" -metaData "DisableSRIOV : Test Iteration - $TestIteration" `
                        -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    }
                    else {
                        LogMsg "Disable Accelerated networking : Failed."
                        $Stage2Result = $false
                        $resultArr += "FAIL"
                        $CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "DisableSRIOV : Test Iteration - $TestIteration" `
                        -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    }
                } else {
                    LogMsg "Test Accelerated networking : Failed."
                    $Stage2Result = $false
                    $resultArr += "FAIL"
                    $CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "DisableSRIOV : Test Iteration - $TestIteration" `
                    -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName                    
                }
            }
            else {
                #Break the for loop.
                $resultArr += "FAIL"
                break;
            }
        }
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        LogErr "EXCEPTION : $ErrorMessage"
    }
    Finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
