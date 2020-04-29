# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param(
    [object] $AllVmData,
    [object] $CurrentTestData,
    [object] $TestProvider,
    [object] $TestParams
)

$TEST_SCRIPT = "perf_lkp.sh"
$LKP_RESULTS = "lkp-results.log"
$LKP_OUPUT = "lkp-output.log"
$LKP_LOG_FILE = "lkp_log.tar"
$LKP_LOG_DIR = "lkp_log"
$VERTICAL_FORMAT_TESTS = @("perf-bench-numa-mem", "pmbench", "aim9")
$MICROBENCHMARK_TEST_NAMES = @("perf-bench-sched-pipe", "perf-bench-numa-mem", "pmbench")

function Get-BenchmarkResult ($testName, $jsonResult) {
    switch ($testName) {
        "hackbench" {
            $resultTitle = "{0,-30} {1,-30}" -f "throughput", "workload"
            $result = "{0,-30} {1,-30}" -f ${jsonResult}.'hackbench.throughput'[0], ${jsonResult}.'hackbench.workload'[0]
        }
        "perf-bench-sched-pipe" {
            $resultTitle = "ops_per_sec"
            $result = ${jsonResult}.'perf-bench-sched-pipe.ops_per_sec'[0]
        }
        "unixbench" {
            $resultTitle = "{0,-30} {1,-30}" -f "score", "workload"
            $result = "{0,-30} {1,-30}" -f ${jsonResult}.'unixbench.score'[0], ${jsonResult}.'unixbench.workload'[0]
        }
        default {
            Write-LogErr "unknow test name of ${testName}"
            return $null,$null
        }
    }
    return $resultTitle, $result
}

function Get-VerticalFormat-TestResult ($currentTestResult, $currentTestData, $testName) {
    try {
        $LogPath = Join-Path $LogDir\$LKP_LOG_DIR $testName
        if (-not (Test-Path -Path $LogPath)) {
            Write-LogErr "EXCEPTION : $LKP_LOG_DIR doesn't exist"
            return $resultAborted
        }

        $items = Get-ChildItem $LogPath
        $items | ForEach-Object {
            $resultPath = Join-Path $LogPath $_
            $resultFile = Join-Path $resultPath "${testName}.json"
            if (-not (Test-Path -Path $resultFile)) {
                Write-LogErr "EXCEPTION : $resultFile doesn't exist"
                return $resultPass
            }

            $metaData = "{0,-30}" -f "$_ Job"
            $result = $null
            $item = "{0,-30} {1,30}" -f $metaData, $result
            Add-Content -Value $item -Path "$LogDir\$LKP_RESULTS"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $result -metaData $metaData `
                    -checkValues "PASS,FAIL,SKIP" -testName $CurrentTestData.testName

            (Get-Content $resultFile) | ConvertFrom-Json > tmp.txt
            $content = Get-Content ".\tmp.txt"
            $content | ForEach-Object {
                $isBlank = [string]::IsNullOrWhiteSpace($_)
                if (-not $isBlank) {
                    $metaData = "    $($_.split(':')[0])"
                    $result = $_.split(":")[1].split("{}")[1]

                    $item = "{0,-30} {1,30}" -f $metaData, $result
                    Add-Content -Value $item -Path "$LogDir\$LKP_RESULTS"
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $result -metaData $metaData `
                            -checkValues "PASS,FAIL,SKIP" -testName $CurrentTestData.testName
                }
            }
            Remove-Item ".\tmp.txt"
        }
        return $resultPass

    } catch {
        Write-LogErr "Getting test summary results failed"
        Remove-Item ".\tmp.txt"
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $errorMessage at line: $errorLine"
        return $resultAborted
    }
}
function Get-HorizontalFormat-TestResult ($currentTestResult, $currentTestData, $testName) {
    try {
        $isResultHead = $true
        $metaDataTitle = "{0,-30}" -f "Jobs"

        $LogPath = Join-Path $LogDir\$LKP_LOG_DIR $testName
        if (-not (Test-Path -Path $LogPath)) {
            Write-LogErr "EXCEPTION : $LKP_LOG_DIR\$testName doesn't exist"
            return $resultAborted
        }

        $items = Get-ChildItem $LogPath
        $items | ForEach-Object {
            $resultPath = Join-Path $LogPath $_
            $resultFile = Join-Path $resultPath "${testName}.json"
            if (-not (Test-Path -Path $resultFile)) {
                Write-LogErr "EXCEPTION : $resultFile doesn't exist"
                return $resultPass
            }
            $jsonResult = (Get-Content $resultFile) | ConvertFrom-Json
            $metaData = "{0,-30}" -f $_
            $resultTitle, $result = Get-BenchmarkResult -testName $testName -jsonResult $jsonResult

            if ($isResultHead) {
                $isResultHead = $false
                $item = "{0,-30} {1,30}" -f $metaDataTitle, $resultTitle
                Add-Content -Value $item -Path "$LogDir\$LKP_RESULTS"
                $CurrentTestResult.TestSummary += New-ResultSummary -testResult $resultTitle -metaData $metaDataTitle `
                        -checkValues "PASS,FAIL,SKIP" -testName $CurrentTestData.testName
            }

            $item = "{0,-30} {1,30}" -f $metaData, $result
            Add-Content -Value $item -Path "$LogDir\$LKP_RESULTS"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $result -metaData $metaData `
                        -checkValues "PASS,FAIL,SKIP" -testName $CurrentTestData.testName
       }

       return $resultPass
    } catch {
        Write-LogErr "Getting test summary results failed"
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $errorMessage at line: $errorLine"
        return $resultAborted
    }
}

function Get-TestResult ($currentTestResult, $currentTestData) {
    try {
        Write-LogInfo "Uncompress $LKP_LOG_FILE..."
        $Compress = .\Tools\7za.exe -y x "$LogDir\$LKP_LOG_FILE" -o"$LogDir"
        if (-not ($Compress -imatch "Everything is Ok")) {
            Write-LogErr "EXCEPTION : Failed to uncompress $LKP_LOG_FILE"
            return $resultAborted
        }

        Write-LogInfo "Parse LKP test results..."
        if ($currentTestData.testName -eq "PERF-LKP-MICROBENCHMARK") {
            $testNameSet = $MICROBENCHMARK_TEST_NAMES
        } else {
            $testName = $($currentTestData.testName).Split("-")[2].ToLower().Replace("_", "-")
            $testNameSet = @("$testName")
        }

        $testNameSet | ForEach-Object {
            $metaData = "{0,-30}" -f $_.ToUpper()
            $result = $null
            $item = "{0,-30} {1,30}" -f $metaData, $result
            Add-Content -Value $item -Path "$LogDir\$LKP_RESULTS"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $result -metaData $metaData `
                    -checkValues "PASS,FAIL,SKIP" -testName $CurrentTestData.testName

            if ($VERTICAL_FORMAT_TESTS.Contains($_)) {
                $result = Get-VerticalFormat-TestResult -currentTestResult $CurrentTestResult -currentTestData $CurrentTestData -testName $_
            } else {
                $result = Get-HorizontalFormat-TestResult -currentTestResult $CurrentTestResult -currentTestData $CurrentTestData -testName $_
            }
        }

        return $result

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
        $null = Run-LinuxCmd -Command "bash ${TEST_SCRIPT} > LKP-summary.log 2>&1" `
            -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
            -maxRetryCount 1 -runMaxAllowedTime 21600 -runAsSudo

        $null = Collect-TestLogs -LogsDestination $LogDir -TestType "sh" `
            -PublicIP $AllVmData.PublicIP -SSHPort $AllVmData.SSHPort `
            -Username $user -password $password `
            -TestName $currentTestData.testName

        # The LKP log will be placed under /root on RedHat when running TEST_SCRIPT with runAsSudo
        # The NULL.log makes sure cp always work on all distros
        $null = Run-LinuxCmd -Command "touch /root/NULL.log && \cp -f /root/*.log /home/${user}" `
                -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
                -maxRetryCount 1 -runAsSudo -ignoreLinuxExitCode

        $filesTocopy = "{0}/${LKP_OUPUT}, {0}/${LKP_LOG_FILE}, {0}/state.txt" -f @("/home/${user}")
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
