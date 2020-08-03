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

function Get-SQLQueryOfLTP ($currentTestResult, $currentTestData) {
    try {
        Write-LogInfo "Generating the test data for database insertion"
        $TestDate = $(Get-Date -Format yyyy-MM-dd)
        $TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
        if (!$TestCaseName) {
            $TestCaseName = $currentTestData.testName
        }

        foreach ($param in $currentTestData.TestParameters.param) {
            if ($param -match "ltp_version_git_tag") {
                $LTPVersion = $param.Replace("ltp_version_git_tag=","").Replace('"',"")
            }

            if ($param -match "LTP_TEST_SUITE") {
                $LTPTestSuite  = $param.Replace("LTP_TEST_SUITE=","").Replace('"',"")
                if ($LTPTestSuite -ne "full") {
                    $LTPTestSuite = "light"
                }
            }
        }

        $isAllTestPass = $True
        $LogPath = Join-Path $LogDir $LTP_RESULTS
        $content = Get-Content $LogPath
        $content | ForEach-Object {
            if ($_ -match "[\w]+\s+(PASS|FAIL|CONF)\s+[\d]+") {
                $rezArray = ($_ -replace '\s+', ' ').Split(" ")
                $currentResult = $rezArray[1]
                $metaData = $rezArray[0]
                if ($currentResult -eq "FAIL") {
                    # Using the script scope modifier to avoid the warning "The variable is assigned but never used"
                    # checked by PSScriptAnalyzer
                    $script:isAllTestPass = $False
                    $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
                        -checkValues "PASS,FAIL,CONF" -testName $CurrentTestData.testName
                }

                $resultMap = @{}
                $resultMap["GuestDistro"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type" `
                                            | ForEach-Object {$_ -replace ",OS type,",""})
                $resultMap["HostOS"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version" `
                                       | ForEach-Object {$_ -replace ",Host Version,",""})
                $resultMap["TestCaseName"] = $TestCaseName
                $resultMap["TestDate"] = $TestDate
                $resultMap["HostType"] = $TestPlatform
                $resultMap["HostBy"] = $currentTestData.SetupConfig.TestLocation
                $resultMap["GuestOSType"] = 'Linux'
                $resultMap["GuestSize"] = $allVMData.InstanceSize
                $resultMap["GuestKernelVersion"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version" `
                                                   | ForEach-Object {$_ -replace ",Kernel version,",""})
                $resultMap["LTPVersion"] = $LTPVersion
                $resultMap["LTPTestItem"] = $metaData
                $resultMap["LTPTestSuite"] = $LTPTestSuite
                $resultMap["TestResult"] = $currentResult

                $currentTestResult.TestResultData += $resultMap
            }
        }
        if ($isAllTestPass) {
            return "PASS"
        } else {
            return "FAIL"
        }
    } catch {
        Write-LogErr "Getting the SQL query of test results failed"
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $errorMessage at line: $errorLine"
        return "ABORTED"
    }
}

function Parse-LTP {
    param (
        [string] $LogPath,
        [string] $XmlDestination,
        [string] $SuiteName = "LTP"
    )

    $suiteName
    $content = Get-Content $LogPath
    $content = $content | Where-Object {$_ -match "[\w]+\s+(PASS|FAIL|CONF)\s+[\d]+"}

    if (-not $content) {
        Write-LogErr "Cannot find LTP test results"
        return
    }

    $testResults = @{}
    $content | ForEach-Object {
                    if ($_ -match "[\w]+\s+(PASS|FAIL|CONF)\s+[\d]+") {
                        $rezArray = ($_ -replace '\s+', ' ').Split(" ")
                        $testResults[$rezArray[0]] = $rezArray[1]
                    }
                }
    if (-not $testResults) {
        Write-LogErr "Could not parse LTP log"
        return
    }

    New-Item $XmlDestination -Force
    $XmlDestination = Resolve-Path $XmlDestination
    $xmlDoc = New-Object System.XML.XMLDocument
    $xmlRoot = $xmlDoc.CreateElement("testsuite")
    if ($SuiteName) {
        $null = $xmlRoot.SetAttribute("name", $SuiteName)
    }
    $null = $xmlDoc.appendChild($xmlRoot)
    foreach ($key in $testResults.Keys) {
        $element = $xmlDoc.CreateElement("testcase")
        $null = $element.SetAttribute("name", $key)

        if ($testResults[$key] -ne "PASS") {
            $failure = $xmlDoc.CreateElement("failure")
            $null = $element.appendChild($failure)
        }

        $null = $xmlRoot.appendChild($element)
    }
    $xmlDoc.Save($XmlDestination)
}

function Main {
    param (
        [object] $AllVmData,
        [object] $CurrentTestData,
        [object] $TestProvider,
        [object] $TestParams
    )

    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        $null = Run-LinuxCmd -Command "bash ${TEST_SCRIPT} > LTP-summary.log 2>&1" `
            -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
            -maxRetryCount 1 -runMaxAllowedTime 12600 -runAsSudo

        $null = Collect-TestLogs -LogsDestination $LogDir -TestType "sh" `
            -PublicIP $AllVmData.PublicIP -SSHPort $AllVmData.SSHPort `
            -Username $user -password $password `
            -TestName $currentTestData.testName

        # The LTP log will be placed under /root on SUSE and RedHat when running TEST_SCRIPT with runAsSudo
        # The NULL.log makes sure cp always work on all distros
        $null = Run-LinuxCmd -Command "touch /root/NULL.log && \cp -f /root/*.log /home/${user}" `
                -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
                -maxRetryCount 1 -runAsSudo -ignoreLinuxExitCode

        $null = Run-LinuxCmd -Command "\cp -f /opt/ltp/VM_properties.csv /home/${user}" `
                -Username $user -password $password -ip $AllVmData.PublicIP -Port $AllVmData.SSHPort `
                -maxRetryCount 1 -runAsSudo

        $filesTocopy = "{0}/${LTP_RESULTS}, {0}/${LTP_OUPUT}, {0}/state.txt,{0}/VM_properties.csv" -f @("/home/${user}")
        Copy-RemoteFiles -download -downloadFrom $AllVmData.PublicIP -downloadTo $LogDir `
            -Port $AllVmData.SSHPort -Username $user -password $password `
            -files $filesTocopy

        $ltpLogPath = Join-Path $LogDir $LTP_RESULTS
        $ltpJunitDest = Join-Path $LogDir "ltp-report.xml"
        $null = Parse-LTP -LogPath $ltpLogPath -XmlDestination $ltpJunitDest
        Copy-Item $ltpJunitDest . -Force

        $statusLogPath = Join-Path $LogDir "state.txt"
        $currentResult = Get-Content $statusLogPath
        if (($currentResult -imatch "TestAborted") -or ($currentResult -imatch "TestRunning")) {
            Write-LogErr "Test aborted. Last known status : $currentResult"
            $resultArr += "ABORTED"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
                -checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
        } else {
            $null = Get-SQLQueryOfLTP -currentTestResult $CurrentTestResult -currentTestData $CurrentTestData
            $resultArr += "PASS"
        }
    } catch {
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $errorMessage at line: $errorLine"
    } finally {
        if (!$resultArr) {
            $resultArr += "ABORTED"
        }
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult

}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider `
    -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))