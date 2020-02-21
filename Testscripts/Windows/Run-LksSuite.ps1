# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param(
    [object] $AllVmData,
    [object] $CurrentTestData,
    [object] $TestProvider,
    [object] $TestParams
)

$TEST_SCRIPT = "Linux-Kernel-Self-Tests.sh"
$LKS_RESULTS = "lks-results.log"
$LKS_OUPUT = "lks-output.log"
$BUILDING_LOG = "lks-building.log"

function Get-TestResult ($currentTestResult, $currentTestData) {
    try {
        Write-LogInfo "Getting test summary results"
        $lksResults="$LogDir\lks-summay-results.log"

        $totalCount = 0
        $totalPass = 0
        $totalSkip = 0
        $totalFail = 0

        $LogPath = Join-Path $LogDir $LKS_RESULTS
        $content = Get-Content $LogPath
        $content | ForEach-Object {
            if ($_ -match "(ok|not ok)+\s+[\d..\d]+\s+(selftests:)\s+[\w|\w-\w:]+\s+[\w|\w-\w|.]+\s+(\[(PASS|FAIL|SKIP)\])") {
                $subsystem = $_.split(":")[1].split(" ")[1]
                $testname = $_.split(":")[2].split(" ")[1]
                $result = $_.split("[]")[1]
                $metaData = $subsystem + "_" + $testname
                $item = "{0,-20} {1,-35} {2,10}" -f $subsystem, $testname, $result
            } elseif ($_ -match "(ok|not ok)+\s+[\d..\d]+\s+(selftests:)\s+[\w|\w-\w|.]+\s+(\[(PASS|FAIL|SKIP)\])") {
                $metaData = $_.split(":")[1].replace(' ','').split('[')[0]
                $result = $_.split("[]")[1]
                $item = "{0,-35} {1,10}" -f $metaData, $result
            } elseif ($_ -match "(ok|not ok)+\s+\d+\s+[\w]") {
                $metaData = $_.split(" ")[2]
                $result = $_.split(" ")[0]

                if ($result -eq "ok") {
                    $result = "PASS"
                } else {
                    $result = "FAIL"
                }

                $item = "{0,-35} {1,10}" -f $metaData, $result
            }
            else {
                Write-LogInfo "Unknown output format"
                continue
            }

            $totalCount += 1
            if ($result -eq "FAIL") {
                $totalFail += 1
                $CurrentTestResult.TestSummary += New-ResultSummary -testResult $result -metaData $metaData `
                        -checkValues "PASS,FAIL,SKIP" -testName $CurrentTestData.testName
            } elseif ($result -eq "PASS") {
                $totalPass += 1
            } elseif ($result -eq "SKIP") {
                $totalSkip += 1
            } else {
                Write-LogInfo "Unknown result format"
            }
            Add-Content -Value $item -Path $lksResults
       }

        $CurrentTestResult.TestSummary += New-ResultSummary -testResult $totalCount -metaData "total test cases" `
                        -checkValues "" -testName $CurrentTestData.testName
        Add-Content -Value "total test cases: $totalCount" -Path $lksResults

        $CurrentTestResult.TestSummary += New-ResultSummary -testResult $totalPass -metaData "total passed" `
                        -checkValues "" -testName $CurrentTestData.testName
        Add-Content -Value "total passed: $totalPass" -Path $lksResults

        $CurrentTestResult.TestSummary += New-ResultSummary -testResult $totalFail -metaData "total failed" `
                        -checkValues "" -testName $CurrentTestData.testName
        Add-Content -Value "total failed: $totalFail" -Path $lksResults

        $CurrentTestResult.TestSummary += New-ResultSummary -testResult $totalSkip -metaData "total skipped" `
                        -checkValues "" -testName $CurrentTestData.testName
        Add-Content -Value "total skipped: $totalSkip" -Path $lksResults

        if ($totalFail -eq 0) {
            return $resultPass
        } else {
            return $resultFail
        }
    } catch {
        Write-LogErr "Getting test summary results failed"
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $errorMessage at line: $errorLine"
        return $resultAborted
    }
}

function Main {
    param (
        [object] $AllVmData,
        [object] $CurrentTestData
    )

    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        $null = Run-LinuxCmd -Command "bash ${TEST_SCRIPT} > LKS-summary.log 2>&1" `
            -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
            -maxRetryCount 1 -runMaxAllowedTime 10800 -runAsSudo

        $null = Collect-TestLogs -LogsDestination $LogDir -TestType "sh" `
            -PublicIP $AllVmData.PublicIP -SSHPort $AllVmData.SSHPort `
            -Username $user -password $password `
            -TestName $currentTestData.testName

        # The LKS log will be placed under /root on RedHat when running TEST_SCRIPT with runAsSudo
        # The NULL.log makes sure cp always work on all distros
        $null = Run-LinuxCmd -Command "touch /root/NULL.log && \cp -f /root/*.log /home/${user}" `
                -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
                -maxRetryCount 1 -runAsSudo -ignoreLinuxExitCode

        $filesTocopy = "{0}/${LKS_RESULTS}, {0}/${LKS_OUPUT}, {0}/${BUILDING_LOG}, {0}/state.txt,{0}/VM_properties.csv" -f @("/home/${user}")
        Copy-RemoteFiles -download -downloadFrom $AllVmData.PublicIP -downloadTo $LogDir `
            -Port $AllVmData.SSHPort -Username $user -password $password `
            -files $filesTocopy

        $statusLogPath = Join-Path $LogDir "state.txt"
        $currentResult = Get-Content $statusLogPath
        if (($currentResult -imatch "TestAborted") -or ($currentResult -imatch "TestRunning")) {
            Write-LogErr "Test aborted. Last known status : $currentResult"
            $resultArr += $resultAborted
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
                -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
        } else {
            $result = Get-TestResult -currentTestResult $CurrentTestResult -currentTestData $CurrentTestData
            $resultArr += $result
        }
    } catch {
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $errorMessage at line: $errorLine"
    } finally {
        if (!$resultArr) {
            $resultArr += $resultAborted
        }
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult

}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData
