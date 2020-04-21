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

    $testResult = $ResultAborted
    $resultArr = @()
    $keyWord = ""
    $CurrentTestResult = Create-TestResultObject

    foreach ($param in $currentTestData.TestParameters.param) {
        $paramName = $param.Split("=")[0]
        $paramValue = $param.Split("=")[1]
        if ($paramName -eq "rebootNumber") {
            $rebootNumber = $paramValue
        }
        if ($paramName -eq "type") {
            $testType = $paramValue
            $expectedCount,$keyWord = Get-ExpectedDevicesCount -vmData $AllVmData -username $user -password $password -type $testType
            Run-LinuxCmd -ip $AllVmData.PublicIP -port $AllVmData.SSHPort -username $user -password $password -command "which lspci || (. ./utils.sh && install_package pciutils)" -runAsSudo | Out-Null
        }
    }
    if (-not $rebootNumber) {
        $rebootNumber = "1"
    }

    $hasIssues = ! (Check-KernelLogs -allVMData $AllVmData)
    if ($hasIssues) {
        $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" `
            -metaData "FirstBoot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        $testResult = $ResultFail
    } else {
        for ($rebootNr = 1; $rebootNr -le $rebootNumber; $rebootNr++) {
            try {
                Write-LogInfo ("Trying to restart {0}: {1} / {2} ..." `
                    -f @($AllVMData.RoleName, $rebootNr, $rebootNumber))
                $isRestarted = $TestProvider.RestartAllDeployments($AllVmData)
                if ($isRestarted) {
                    Write-LogInfo "Virtual machine restart successful."
                    $hasIssues = ! (Check-KernelLogs -allVMData $AllVmData)
                    if ($hasIssues) {
                        $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" `
                            -metaData "The $rebootNr Reboot: Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                        $testResult = $ResultFail
                        break
                    } else {
                        if ($testType) {
                            $pciDevices = Run-LinuxCmd -ip $AllVmData.PublicIP -port $AllVmData.SSHPort -username $user -password $password -command "lspci | grep -i '$keyWord' | wc -l" -runAsSudo -ignoreLinuxExitCode
                            Write-LogInfo "Actual count: $pciDevices, expected count: $expectedCount"
                            if ($pciDevices -ne $expectedCount) {
                                $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" `
                                    -metaData "The $rebootNr Reboot: lspci return values are not expected" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                                $testResult = $ResultFail
                                break
                            }
                        }
                    }
                } else {
                    Write-LogErr "Virtual machine restart failed."
                    $testResult = $ResultFail
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" `
                        -metaData "The $rebootNr Reboot fail" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break
                }
            } catch {
                $ErrorMessage =  $_.Exception.Message
                $ErrorLine = $_.InvocationInfo.ScriptLineNumber
                Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
                break
            }
        }
        $rebootNr--
        Write-LogInfo "Reboot Stress Test Result: $rebootNr/$rebootNumber"
        if ($rebootNr -lt $rebootNumber) {
            $testResult = $ResultFail
        } else {
            $testResult = $ResultPass
        }
    }
    $resultArr += $testResult
    Write-LogInfo "Test result : $testResult"
    $CurrentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $CurrentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider
