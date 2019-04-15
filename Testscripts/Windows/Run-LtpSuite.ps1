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
        -maxRetryCount 1 -runMaxAllowedTime 10000 -runAsSudo

    $null = Collect-TestLogs -LogsDestination $LogDir -TestType "sh" `
        -PublicIP $AllVmData.PublicIP -SSHPort $AllVmData.SSHPort `
        -Username $user -password $password `
        -TestName $currentTestData.testName

    $filesTocopy = "{0}/${LTP_RESULTS}, {0}/${LTP_OUPUT}" -f @("/home/${username}")
    Copy-RemoteFiles -download -downloadFrom $AllVmData.PublicIP -downloadTo $LogDir `
        -Port $AllVmData.SSHPort -Username $user -password $password `
        -files $filesTocopy

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

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult

}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider `
    -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))