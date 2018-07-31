# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result 
    $result = ""
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        LogMsg "Trying to shut down $($AllVMData.RoleName)..."
        if ($UseAzureResourceManager) {
            $stopVM = Stop-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -Force -StayProvisioned -Verbose
            if ($?) {
                $isStopped = $true
            } else {
                $isStopped = $false
            }
        } else {
            $out = StopAllDeployments -DeployedServices $isDeployed
            $isStopped = $?
        }
        if ($isStopped) {
            LogMsg "Virtual machine shut down successful."
            $testResult = "PASS"
        } else {
            LogErr "Virtual machine shut down failed."
            $testResult = "FAIL"
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
