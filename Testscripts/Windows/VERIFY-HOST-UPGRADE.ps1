# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([object] $AllVmData,
      [object] $CurrentTestData,
      [object] $TestProvider)

function Main {
    param(
        [parameter(Mandatory=$true)]
        [object] $AllVmData,
        [parameter(Mandatory=$true)]
        [object] $CurrentTestData,
        [parameter(Mandatory=$true)]
        [object] $TestProvider
    )

    $resultArr = @()
    $testResult = $ResultFail
    $CurrentTestResult = Create-TestResultObject
    $rebootCount = 0
    
    $hasIssues = ! (Check-KernelLogs -allVMData $AllVmData)
    if ($hasIssues) {
        $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" `
            -metaData "FirstBoot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
    } else {
        # Get the host version
        $oldHostVersion = Run-LinuxCmd -ip $AllVMData[0].PublicIP -port $AllVMData[0].SSHPort -username $user -password $password ". utils.sh && get_host_version" -runAsSudo
        Write-LogInfo "VM host version is: $oldHostVersion"
        # Start the timer
        $StartTime = Get-Date
        for (;; $rebootCount++) {
            try {
                Write-LogInfo ("Restarting VM {0} - count {1} ..." `
                    -f @($AllVMData.RoleName, $rebootCount))
                $isRestarted = $TestProvider.RestartAllDeployments($AllVmData)
                if ($isRestarted) {
                    Write-LogInfo "VM restarted successfully"
                    $hasIssues = ! (Check-KernelLogs -allVMData $AllVmData)
                    if ($hasIssues) {
                        $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" `
                            -metaData "The $rebootCount Reboot: Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                        break
                    } else {
                        # Check host version
                        # 1. Host version changed then host is updated, exit test
                        $newHostVersion = Run-LinuxCmd -ip $AllVMData[0].PublicIP -port $AllVMData[0].SSHPort -username $user -password $password ". utils.sh && get_host_version" -runAsSudo
                        Write-LogInfo "Current VM host version is: $newHostVersion"
                        if ($oldHostVersion -ne $newHostVersion) {
                            Write-LogInfo "VM host version is updated. New Host version: $newHostVersion"
                            $testResult = $ResultPass
                            break
                        }
                        # 2. Check if the allowed time exceeded then fail and exit the test
                        $timespan = New-TimeSpan -Start $StartTime -End (Get-Date)
                        $elapsedtimeMinutes = ($timespan.Hours*60) + $timespan.Minutes
                        if ($elapsedtimeMinutes -ge 120) {
                            Write-LogInfo "VM host version not updated after 2 hours"
                            break
                        }
                    } 
                } else {
                    Write-LogErr "Virtual machine restart failed."
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" `
                        -metaData "The $rebootCount Reboot fail" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                    break
                }
            } catch {
                $ErrorMessage =  $_.Exception.Message
                $ErrorLine = $_.InvocationInfo.ScriptLineNumber
                Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
                break
            }
        }
    }
    $resultArr += $testResult
    Write-LogInfo "Test result : $testResult"
    $CurrentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $CurrentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider
