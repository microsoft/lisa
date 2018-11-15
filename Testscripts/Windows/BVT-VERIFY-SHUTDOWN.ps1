# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        LogMsg "Trying to shut down $($AllVMData.RoleName)..."
        $null = Stop-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -Force -StayProvisioned -Verbose
        if ($?) {
            LogMsg "Virtual machine shut down successful."
            $testResult = "PASS"

            # Start the VM again for collect distro logs
            LogMsg "Trying to start $($AllVMData.RoleName) to collect logs..."
            $null = Start-AzureRmVM -ResourceGroup $AllVMData.ResourceGroupName -name $AllVMData.RoleName
            # Refresh the data in case public IP address changes
            $global:AllVMData = GetAllDeployementData -ResourceGroups $AllVMData.ResourceGroupName

            $isSSHOpened = isAllSSHPortsEnabledRG -AllVMDataObject $AllVMData
            if (!$isSSHOpened) {
                $global:isDeployed = $null
                LogMsg "Failed to connect to $($AllVMData.RoleName), set global variable isDeployed to null $global:isDeployed"
            }
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogMsg "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
