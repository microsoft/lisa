# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param(
    [object] $AllVmData,
    [object] $CurrentTestData,
    [object] $TestProvider,
    [object] $TestParams
)

$TEST_SCRIPT = "Linux-Test-Project-Tests.sh"
$LTP_RESULTS = "ltp-results.log"
$LTP_OUPUT = "ltp-output.log"

function Main {
    param (
        [object] $AllVmData,
        [object] $CurrentTestData,
        [object] $TestProvider,
        [object] $TestParams
    )

    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    $null = Run-LinuxCmd -Command "bash ${TEST_SCRIPT} > LTP-summary.log 2>&1" `
        -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
        -maxRetryCount 1 -runMaxAllowedTime 12600 -runAsSudo

    $null = Collect-TestLogs -LogsDestination $LogDir -TestType "sh" `
        -PublicIP $AllVmData.PublicIP -SSHPort $AllVmData.SSHPort `
        -Username $user -password $password `
        -TestName $currentTestData.testName

    # The LTP log will be placed under /root on SUSE and RedHat when running TEST_SCRIPT with runAsSudo
    # The NULL.log makes sure cp always work on all distros
    $null = Run-LinuxCmd -Command "touch /root/NULL.log && cp -n /root/*.log /home/${user}" `
            -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
            -maxRetryCount 1 -runAsSudo

    $filesTocopy = "{0}/${LTP_RESULTS}, {0}/${LTP_OUPUT}, {0}/state.txt" -f @("/home/${user}")
    Copy-RemoteFiles -download -downloadFrom $AllVmData.PublicIP -downloadTo $LogDir `
        -Port $AllVmData.SSHPort -Username $user -password $password `
        -files $filesTocopy

    $statusLogPath = Join-Path $LogDir "state.txt"
    $currentResult = Get-Content $statusLogPath
    if (($currentResult -imatch "TestAborted") -or ($currentResult -imatch "TestRunning")) {
        Write-LogErr "Test aborted. Last known status : $currentResult"
        $resultArr += "Aborted"
        $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
            -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
    } else {
        $LogPath = Join-Path $LogDir $LTP_RESULTS
        $content = Get-Content $LogPath
        $content | ForEach-Object {
            if ($_ -match "[\w]+\s+(PASS|FAIL|CONF)\s+[\d]+") {
                $rezArray = ($_ -replace '\s+', ' ').Split(" ")
                $currentResult = $rezArray[1]
                $metaData = $rezArray[0]
                if ($currentResult -eq "FAIL") {
                    $resultArr += $currentResult
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
                        -checkValues "PASS,FAIL,CONF" -testName $CurrentTestData.testName
                }
            }
        }
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult

}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider `
    -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))