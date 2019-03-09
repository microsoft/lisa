# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData)

function Main {
    param([object] $AllVMData)
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        Write-LogInfo "Trying to restart $($AllVMData.RoleName)..."
        $restartVM = Restart-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -Verbose
        if ( $restartVM.Status -eq "Succeeded" ) {
            $isVmAlive = Is-VmAlive -AllVMDataObject $AllVMData
            if ($isVmAlive -eq "True") {
                $isRestarted = $true
            } else {
                Write-LogErr "VM is not available after restart"
                $isRestarted = $false
            }
        } else {
            $isRestarted = $false
            Write-LogErr "Restart Failed. Operation ID : $($restartVM.OperationId)"
        }
        if ($isRestarted) {
            Write-LogInfo "Virtual machine restart successful."
            $testResult = "PASS"
        } else {
            Write-LogErr "Virtual machine restart failed."
            $testResult = "FAIL"
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
    return $currentTestResult
}

Main -AllVMData $AllVmData
