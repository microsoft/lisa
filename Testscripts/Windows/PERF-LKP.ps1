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
$BENCHMARK_DESC = @{
    "hackbench" = "It's main job is to create a specified number of pairs of schedulable entities `
                  (either threads or traditional processes) which communicate via either sockets `
                  or pipes and time how long it takes for each pair to send data back and forth. `
                  100%,1600%,50% as below means the percentage of the threads number and the cpus number";
    "unixbench" = "The purpose of UnixBench is to provide a basic indicator of the performance of `
                  a Unix-like system; These test results are then compared to the scores from a `
                  baseline system to produce an index value. `
                  '1' as below means the threads number is the same with the cpus number.";
    "aim9" = "The AIM Independent Resource Benchmark exercises and times each component of a UNIX `
                  computer system, independently. The benchmark uses 58 subtests to generate absolute processing rates,`
                  in operations per second, for subsystems, I/O transfers, function calls, and UNIX system calls.";
    "perf-bench-sched-pipe" = "The loop number is 10000000. It has 'process' and 'threads' mode.";
    "perf-bench-numa-mem" = "NUMA scheduling and MM benchmarks. The size of processed memory is 300M `
                  The threads number is 2. ";
    "pmbench" = "pmbench is a micro-benchmark that profiles system paging performance by measuring `
                  latencies of each memory access throughout the run and reporting the statistics of measured latencies.`
                  The benchmark creates a free_mem * 75% GiB memory map and then accesses only the first 128MB with runtime `
                  is 300s. 0-256% as below means the percentage of the accesses that took between 0~256 ns and all the accesses."}
$FORMAT_ALIGN_SIZE = 30

function Get-BenchmarkResult ($testName, $jsonResult) {
    switch ($testName) {
        "hackbench" {
            $job_desc = "{0,-$FORMAT_ALIGN_SIZE}" -f "(IPC-mode-threads)"
            $result_desc = "(throughput)"
            $result = ${jsonResult}.'hackbench.throughput'[0]
        }
        "perf-bench-sched-pipe" {
            $job_desc = "{0,-$FORMAT_ALIGN_SIZE}" -f "(loops-mode)"
            $result_desc = "(ops per second)"
            $result = ${jsonResult}.'perf-bench-sched-pipe.ops_per_sec'[0]
        }
        "unixbench" {
            $job_desc = "{0,-$FORMAT_ALIGN_SIZE}" -f "(threads-runtime-testname)"
            $result_desc = "(system benchmarks index score)"
            $result = ${jsonResult}.'unixbench.score'[0]
        }
        default {
            Write-LogErr "unknow test name of ${testName}"
            return $null,$null
        }
    }
    return $job_desc, $result_desc, $result
}

function Get-VerticalFormat-TestResult ($currentTestResult, $currentTestData, $testName) {
    try {
        $LogPath = Join-Path $LogDir\$LKP_LOG_DIR $testName
        if (-not (Test-Path -Path $LogPath)) {
            throw- "$LKP_LOG_DIR\$testName doesn't exist"
        }

        $items = Get-ChildItem $LogPath
        $items | ForEach-Object {
            $resultPath = Join-Path $LogPath $_
            $resultFile = Join-Path $resultPath "${testName}.json"
            if (-not (Test-Path -Path $resultFile)) {
                Write-LogErr "EXCEPTION : $resultFile doesn't exist"
                return $resultPass
            }

            (Get-Content $resultFile) | ConvertFrom-Json > tmp.txt
            $content = Get-Content ".\tmp.txt"
            $content | ForEach-Object {
                $isBlank = [string]::IsNullOrWhiteSpace($_)
                if (-not $isBlank) {
                    $metaData = "    $($_.split(':')[0])"
                    $result = $_.split(":")[1].split("{}")[1]

                    $item = "{0,-$FORMAT_ALIGN_SIZE} {1,$FORMAT_ALIGN_SIZE}" -f $metaData, $result
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

        $LogPath = Join-Path $LogDir\$LKP_LOG_DIR $testName
        if (-not (Test-Path -Path $LogPath)) {
            throw "$LKP_LOG_DIR\$testName doesn't exist"
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
            $metaData = "{0,-$FORMAT_ALIGN_SIZE}" -f $_
            $job_desc, $result_desc, $result = Get-BenchmarkResult -testName $testName -jsonResult $jsonResult

            if ($isResultHead) {
                $isResultHead = $false
                $item = "{0,-$FORMAT_ALIGN_SIZE} {1,$FORMAT_ALIGN_SIZE}" -f $job_desc, $result_desc
                Add-Content -Value $item -Path "$LogDir\$LKP_RESULTS"
                $CurrentTestResult.TestSummary += New-ResultSummary -testResult $result_desc -metaData $job_desc `
                        -checkValues "PASS,FAIL,SKIP" -testName $CurrentTestData.testName
            }

            $item = "{0,-$FORMAT_ALIGN_SIZE} {1,$FORMAT_ALIGN_SIZE}" -f $metaData, $result
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
            $metaData = "`n`tBenchmark Name"
            $result = $_
            $item = "$metaData : $result"
            Add-Content -Value $item -Path "$LogDir\$LKP_RESULTS"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $result -metaData $metaData `
                    -checkValues "PASS,FAIL,SKIP" -testName $CurrentTestData.testName

            $metaData = "Description"
            $result = "$($BENCHMARK_DESC[$_])`n"
            $item = "$metaData : $result"
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
