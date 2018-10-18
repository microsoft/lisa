# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result 
    $result = ""
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        LogMsg "Trying to restart $($AllVMData.RoleName)..."
        if ($UseAzureResourceManager) {
            $restartVM = Restart-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -Verbose
            if ( $restartVM.Status -eq "Succeeded" ) {
                $isSSHOpened = isAllSSHPortsEnabledRG -AllVMDataObject $AllVMData
                if ($isSSHOpened -eq "True") {
                    $isRestarted = $true
                } else {
                    LogErr "VM is not available after restart"
                    $isRestarted = $false
                }
            } else {
                $isRestarted = $false
                LogErr "Restart Failed. Operation ID : $($restartVM.OperationId)"
            }
        } else {
            $out = RestartAllDeployments -DeployedServices $isDeployed
            $isRestarted = $?
        }
        if ($isRestarted) {
            LogMsg "Virtual machine restart successful."
            $testResult = "PASS"
        } else {
            LogErr "Virtual machine restart failed."
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
