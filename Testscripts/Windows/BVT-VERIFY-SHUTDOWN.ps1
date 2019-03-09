# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData)

function Main {
    param([object] $AllVMData)
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        Write-LogInfo "Trying to shut down $($AllVMData.RoleName)..."
        $null = Stop-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -Force -StayProvisioned -Verbose
        if ($?) {
            Write-LogInfo "Virtual machine shut down successful."
            $testResult = "PASS"

            # Start the VM again for collect distro logs
            Write-LogInfo "Trying to start $($AllVMData.RoleName) to collect logs..."
            $null = Start-AzureRmVM -ResourceGroup $AllVMData.ResourceGroupName -name $AllVMData.RoleName
            # Refresh the data in case public IP address changes
            $vmData = Get-AllDeploymentData -ResourceGroups $AllVMData.ResourceGroupName
            $AllVMData.PublicIP = $vmData.PublicIP

            $isVmAlive = Is-VmAlive -AllVMDataObject $AllVMData
            if ($isVmAlive -eq "False") {
                Write-LogInfo "Failed to connect to $($AllVMData.RoleName)"
                $testResult = "FAIL"
            }
        }
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
    return $currentTestResult.TestResult
}

Main -AllVMData $AllVmData
