# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData,
      [object] $CurrentTestData)

Function Get-SyscallResultObject ()
{
    $Object = New-Object PSObject
    $Object | Add-Member -MemberType NoteProperty -Name test -Value $null
    $Object | Add-Member -MemberType NoteProperty -Name avgReal -Value $null
    $Object | Add-Member -MemberType NoteProperty -Name avgUser -Value $null
    $Object | Add-Member -MemberType NoteProperty -Name avgSystem -Value $null
    return $Object
}
function Main {
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        $testVMData = $allVMData
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        $superUser = "root"

        $myString = @"
# cd /root/
chmod +x perf_syscallbenchmark.sh
./perf_syscallbenchmark.sh &> syscallConsoleLogs.txt
. utils.sh
collect_VM_properties
"@

        Set-Content "$LogDir\StartSysCallBenchmark.sh" $myString
        Copy-RemoteFiles -uploadTo $testVMData.PublicIP -port $testVMData.SSHPort -files "$LogDir\StartSysCallBenchmark.sh" -username $superUser -password $password -upload
        Run-LinuxCmd -ip $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -command "chmod +x *.sh" | Out-Null
        $testJob = Run-LinuxCmd -ip $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -command "./StartSysCallBenchmark.sh" -RunInBackground
        #endregion

        #region MONITOR TEST
        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = Run-LinuxCmd -ip $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -command "tail -1 syscallConsoleLogs.txt"
            Write-LogInfo "Current Test Status : $currentStatus"
            Wait-Time -seconds 20
        }

        $finalStatus = Run-LinuxCmd -ip $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -command "cat state.txt"
        Copy-RemoteFiles -downloadFrom $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -download -downloadTo $LogDir -files "*.txt,*.log,*.csv"
        $testSummary = $null
        #endregion

        if ($finalStatus -imatch "TestFailed") {
            Write-LogErr "Test failed. Last known status : $currentStatus."
            $testResult = "FAIL"
        }
        elseif ($finalStatus -imatch "TestAborted") {
            Write-LogErr "Test Aborted. Last known status : $currentStatus."
            $testResult = "ABORTED"
        }
        elseif ($finalStatus -imatch "TestCompleted") {
            Copy-RemoteFiles -downloadFrom $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -download -downloadTo $LogDir -files "syscall-benchmark-*.tar.gz"
            Write-LogInfo "Test Completed."
            $testResult = "PASS"
            try {
                $logFilePath = "$LogDir\results.log"
                $logs = Get-Content -Path $logFilePath
                $vmInfo = Get-Content -Path $logFilePath | Select-Object -First 2
                $logs = $logs.Split("`n")
                $finalResult = @()
                $finalResult += "************************************************************************"
                $finalResult += " 	SYSCALL BENCHMARK TEST RESULTS 	"
                $finalResult += "************************************************************************"
                $finalResult += $vmInfo
                $currentResult = Get-SyscallResultObject

                foreach ($line in $logs)
                {
                    switch -Regex ($line)
                    {
                        'bench_00_null_call_regs' {
                            $currentResult.test = "bench_00_null_call_regs"
                        }
                        'bench_00_null_call_regs' {
                            $currentResult.test = "bench_00_null_call_regs"
                        }
                        'bench_01_null_call_stack' {
                            $currentResult.test = "bench_01_null_call_stack"
                        }
                        'bench_02_getpid_syscall' {
                            $currentResult.test = "bench_02_getpid_syscall"
                        }
                        'bench_03_getpid_vdso' {
                            $currentResult.test = "bench_03_getpid_vdso"
                        }
                        'bench_10_read_syscall' {
                            $currentResult.test = "bench_10_read_syscall"
                        }
                        'bench_11_read_vdso' {
                            $currentResult.test = "bench_11_read_vdso"
                        }
                        'bench_12_read_stdio' {
                            $currentResult.test = "bench_12_read_stdio"
                        }
                        'bench_20_write_syscall' {
                            $currentResult.test = "bench_20_write_syscall"
                        }
                        'bench_21_write_vdso' {
                            $currentResult.test = "bench_21_write_vdso"
                        }
                        'bench_22_write_stdio' {
                            $currentResult.test = "bench_22_write_stdio"
                        }
                        'average' {
                            $testType = $currentResult.test
                            $currentResult.avgReal = $avgReal = $line.Split(" ")[2]
                            $currentResult.avgUser = $avgUser = $line.Split(" ")[4]
                            $currentResult.avgSystem = $avgSystem = $line.Split(" ")[6]
                            $finalResult += $currentResult
                            $metadata = "test=$testType"
                            $syscallResult = "AverageReal=$avgReal AverageUser=$avgUser AverageSystem=$avgSystem"
                            $resultSummary +=  New-ResultSummary -testResult "$syscallResult : Completed" -metaData $metadata -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                            if ( $currentResult.test -imatch "bench_22_write_stdio") {
                                Write-LogInfo "Syscall results parsing is Done..."
                                break
                            }
                            $currentResult = Get-SyscallResultObject
                        }
                        default {
                            continue
                        }
                    }
                }
                Set-Content -Value ($finalResult | Format-Table | Out-String) -Path "$LogDir\syscalResults.txt"
                Write-Host ($finalResult | Format-Table | Out-String)

                Write-LogInfo "Uploading test results to Database.."
                $dataTableName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbtable
                $TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
                $GuestDistro    = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""}
                $HostType = "$TestPlatform"
                $HostBy = ($global:TestLocation).Replace('"','')
                $HostOS = Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version"| ForEach-Object{$_ -replace ",Host Version,",""}
                $GuestOSType    = "Linux"
                $GuestDistro    = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""}
                $GuestSize = $testVMData.InstanceSize
                $KernelVersion  = Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version"| ForEach-Object{$_ -replace ",Kernel version,",""}
                $LisVersion  = Get-Content "$LogDir\VM_properties.csv" | Select-String "LIS Version"| ForEach-Object{$_ -replace ",LIS Version,",""}
                $cpuInfo = Get-Content -Path $logFilePath | Select-Object -First 1
                $SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,GuestOSType,GuestDistro,GuestSize,KernelVersion,LISVersion,CPU,SyscallTest,CpuUsageAvgReal,CpuUsageAvgUser,CpuUsageAvgSystem) VALUES "
                for ($i = 1; $i -lt $finalResult.Count; $i++) {
                    if ($finalResult[$i].test){
                        $SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$GuestOSType','$GuestDistro','$GuestSize','$KernelVersion','$LisVersion','$cpuInfo','$($finalResult[$i].test)',$($finalResult[$i].avgReal),$($finalResult[$i].avgUser),$($finalResult[$i].avgSystem)),"
                    } else {
                        continue
                    }
                }
                $SQLQuery = $SQLQuery.TrimEnd(',')
                Upload-TestResultToDatabase ($SQLQuery)
            } catch {
                $ErrorMessage =  $_.Exception.Message
                $ErrorLine = $_.InvocationInfo.ScriptLineNumber
                Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
            }
        }
        elseif ($finalStatus -imatch "TestRunning") {
            Write-LogInfo "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
            Write-LogInfo "Contents of summary.log : $testSummary"
            $testResult = "PASS"
        }
        Write-LogInfo "Test result : $testResult"
        Write-LogInfo "Test Completed"
        $currentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        $metaData = "SYSCALL RESULT"
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
