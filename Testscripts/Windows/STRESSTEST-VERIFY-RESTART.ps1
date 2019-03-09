# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([object] $AllVmData,
      [object] $CurrentTestData,
      [object] $TestProvider)

$ErrorActionPreference = "Continue"

function Main {
    param(
        [parameter(Mandatory=$true)]
        [object] $AllVmData,
        [parameter(Mandatory=$true)]
        [object] $CurrentTestData,
        [parameter(Mandatory=$true)]
        [object] $TestProvider
    )

    $result = ""
    $testResult = ""
    $resultArr = @()

    foreach ($param in $currentTestData.TestParameters.param) {
        $paramName = $param.Split("=")[0]
        $paramValue = $param.Split("=")[1]
        if ($paramName -eq "rebootNumber") {
            $rebootNumber = $paramValue
        }
    }
    if (-not $rebootNumber) {
        $rebootNumber = "1"
    }
    for ($rebootNr = 1; $rebootNr -le $rebootNumber; $rebootNr++) {
        try {
            Write-LogInfo ("Trying to restart {0}: {1} / {2} ..." `
                -f @($AllVMData.RoleName, $rebootNr, $rebootNumber))
            $isRestarted = $TestProvider.RestartAllDeployments($allVMData)
            if ($isRestarted) {
                Write-LogInfo "Virtual machine restart successful."
                $testResult = "PASS"
            } else {
                Write-LogErr "Virtual machine restart failed."
                $testResult = "FAIL"
                break
            }
        } catch {
            $ErrorMessage =  $_.Exception.Message
            $ErrorLine = $_.InvocationInfo.ScriptLineNumber
            Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
            break
        } finally {
            if (-not $testResult) {
                $testResult = "Aborted"
            }
            $resultArr += $testResult
        }
    }
    $rebootNr--
    Write-LogInfo "Reboot Stress Test Result: $rebootNr/$rebootNumber"
    if (($rebootNr - 1) -lt $rebootNumber) {
        $testResult = "FAIL"
    }

    $result = Get-FinalResultHeader -resultarr $resultArr
    # Return the result and summary to the test suite script..
    return $result
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider
