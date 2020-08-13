# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param(
    [String] $TestParams,
    [object] $AllVMData,
    [object] $CurrentTestData
)

function Main {
    param (
        $TestParams,
        $AllVMData
    )
    # Create test result
    $CurrentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        $testName="scheduler"
        $myString = @"
./perf_scheduler.sh &> schedulerConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
        Set-Content "$LogDir\Start${testName}Test.sh" $myString
        Copy-RemoteFiles -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort `
            -files "$constantsFile,$LogDir\Start${testName}Test.sh" -username $user -password $password -upload
        Copy-RemoteFiles -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort `
            -files $currentTestData.files -username $user -password $password -upload

        Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password `
            -command "chmod +x *.sh" -runAsSudo | Out-Null
        $testJob = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password `
            -command "./Start${testName}Test.sh" -RunInBackground -runAsSudo

        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password `
                -command "tail -2 ${testName}ConsoleLogs.txt | head -1"
            Write-LogInfo "Current Test Status : $currentStatus"
            Wait-Time -seconds 20
        }
        $finalStatus = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password `
            -command "cat ./state.txt"

        $filesTocopy = "${testName}ConsoleLogs.txt, hackbench.*.log, schbench.*.log, results*.log, results*.csv, VM_properties.csv"
        Copy-RemoteFiles -download -downloadFrom $AllVmData.PublicIP -downloadTo $LogDir -Port $AllVmData.SSHPort `
            -Username $user -password $password -files $filesTocopy

        ##################################################################################################################
        #region Parse log to obtain the test results
        ##################################################################################################################
        $uploadResults = $true
        $hackbench_results = Get-Content -Path "$LogDir\results_hackbench.log"
        $schbench_results = Get-Content -Path "$LogDir\results_schbench.log"

        $connResult = "======================================="
        $metadata = "Hackbench test results"
        $currentTestResult.TestSummary += New-ResultSummary -testResult $connResult -metaData $metadata -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        foreach ($line in $hackbench_results) {
            if ($line -imatch "TestMode") {
                continue;
            }
            try {
                $datasize_bytes = ($line.Trim() -Replace " +"," ").Split(" ")[1]
                $hackbenchType = ($line.Trim() -Replace " +"," ").Split(" ")[5]
                $latency_sec = ($line.Trim() -Replace " +"," ").Split(" ")[6]
                $connResult = "DataSize_bytes=$datasize_bytes Latency_sec=$latency_sec"
                $metadata = "HackbenchType=$hackbenchType"
                $currentTestResult.TestSummary += New-ResultSummary -testResult $connResult -metaData $metadata -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName

                if ([float]$latency_sec -eq 0) {
                    $uploadResults = $false
                    $testResult = "FAIL"
                }
            } catch {
                $ErrorMessage = $_.Exception.Message
                $ErrorLine = $_.InvocationInfo.ScriptLineNumber
                Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
                $currentTestResult.TestSummary += New-ResultSummary -testResult "Error in parsing logs." -metaData "Hackbench" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            }
        }
        $connResult = "======================================="
        $metadata = "Schbench test results"
        $currentTestResult.TestSummary += New-ResultSummary -testResult $connResult -metaData $metadata -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        foreach ($line in $schbench_results) {
            if ($line -imatch "TestMode") {
                continue;
            }
            try {
                $messageThreads = ($line.Trim() -Replace " +"," ").Split(" ")[2]
                $latency95th_us = ($line.Trim() -Replace " +"," ").Split(" ")[3]
                $latency99th_us = ($line.Trim() -Replace " +"," ").Split(" ")[4]
                $connResult = "Latency95thPercentile_us=$latency95th_us Latency99thPercentile_us=$latency99th_us"
                $metadata = "MessageThreads=$messageThreads"
                $currentTestResult.TestSummary += New-ResultSummary -testResult $connResult -metaData $metadata -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName

                if ([float]$latency95th_us -eq 0 -or [float]$latency99th_us -eq 0) {
                    $uploadResults = $false
                    $testResult = "FAIL"
                }
            } catch {
                $ErrorMessage = $_.Exception.Message
                $ErrorLine = $_.InvocationInfo.ScriptLineNumber
                Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
                $currentTestResult.TestSummary += New-ResultSummary -testResult "Error in parsing logs." -metaData "Schbench" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            }
        }
        ##################################################################################################################
        #endregion Parse log to obtain the test results
        ##################################################################################################################

        if ($finalStatus -imatch "TestFailed") {
            Write-LogErr "Test failed. Last known status : $currentStatus."
            $testResult = "FAIL"
        } elseif ($finalStatus -imatch "TestAborted") {
            Write-LogErr "Test Aborted. Last known status : $currentStatus."
            $testResult = "ABORTED"
        } elseif (($finalStatus -imatch "TestCompleted") -and $uploadResults) {
            $testResult = "PASS"
        } elseif ($finalStatus -imatch "TestRunning") {
            Write-LogInfo "Powershell background job is completed but VM is reporting that test is still running. Please check $LogDir\ConsoleLogs.txt"
            $testResult = "ABORTED"
        }

        #region Show results*.csv
        $hackbenchDataCsv = Import-Csv -Path $LogDir\results_hackbench.csv
        Write-LogInfo ("`n**************************************************************************`n"+$CurrentTestData.testName+" RESULTS...`n**************************************************************************")
        Write-Host ($hackbenchDataCsv | Format-Table * | Out-String)
        $schbenchDataCsv = Import-Csv -Path $LogDir\results_schbench.csv
        Write-LogInfo ("`n**************************************************************************`n"+$CurrentTestData.testName+" RESULTS...`n**************************************************************************")
        Write-Host ($schbenchDataCsv | Format-Table * | Out-String)
        #endregion Show results*.csv

        ##################################################################################################################
        #region Parse log then upload the test results to database
        ##################################################################################################################
        $LogContents = @()
        $LogContents += Get-Content -Path "$LogDir\results_hackbench.log"
        $LogContents += Get-Content -Path "$LogDir\results_schbench.log"

        if ($testResult -eq "PASS") {
            $TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
            if (!$TestCaseName) {
                $TestCaseName = $CurrentTestData.testName
            }
            $HostOs =  $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version"| ForEach-Object{$_ -replace ",Host Version,",""})
            $GuestDistro = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""})
            $KernelVersion = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version"| ForEach-Object{$_ -replace ",Kernel version,",""})
            $TestDate = $(Get-Date -Format yyyy-MM-dd)

            Write-LogInfo "Generating the performance data for database insertion"
            foreach ($LogCon in $LogContents) {
                for ($i = 1; $i -lt $LogCon.Count; $i++) {
                    $Line = $LogCon[$i].Trim() -split '\s+'
                    $resultMap = @{}
                    $resultMap["TestCaseName"] = $TestCaseName
                    $resultMap["TestDate"] = $TestDate
                    $resultMap["HostType"] = $TestPlatform
                    $resultMap["HostBy"] = $CurrentTestData.SetupConfig.TestLocation
                    $resultMap["HostOS"] = $HostOs
                    $resultMap["GuestOS"] = $GuestDistro
                    $resultMap["InstanceSize"] = $clientVMData.InstanceSize
                    $resultMap["KernelVersion"] = $KernelVersion
                    $resultMap["TestMode"] = $($Line[0])
                    if ($line[0] -imatch "hackbench") {
                        $resultMap["DataSize_bytes"] = [Decimal]$($Line[1])
                        $resultMap["Loops"] = [Decimal]$($Line[2])
                        $resultMap["Groups"] = [Decimal]$($Line[3])
                        $resultMap["HackbenchType"] = $($Line[5])
                        $resultMap["Latency_sec"] = [Decimal]$($Line[6])
                    } elseif ($line[0] -imatch "schbench") {
                        $resultMap["WorkerThreads"] = [Decimal]$($Line[1])
                        $resultMap["MessageThreads"] = [Decimal]$($Line[2])
                        $resultMap["Latency95thPercentile_us"] = [Decimal]$($Line[3])
                        $resultMap["Latency99thPercentile_us"] = [Decimal]$($Line[4])
                    }
                    $currentTestResult.TestResultData += $resultMap
                }
            }
        }
        ##################################################################################################################
        #endregion Parse log then upload the test results to database
        ##################################################################################################################
        Write-LogInfo "Test result : $testResult"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        $metaData = "${testName} RESULT"
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVMData $AllVmData
