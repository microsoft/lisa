# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

Function Get_Syscall_Result_Object ()
{
    $Object = New-Object PSObject
    $Object | add-member -MemberType NoteProperty -Name test -Value $null
    $Object | add-member -MemberType NoteProperty -Name avgReal -Value $null
    $Object | add-member -MemberType NoteProperty -Name avgUser -Value $null
    $Object | add-member -MemberType NoteProperty -Name avgSystem -Value $null
    return $Object
}
function Main {
    # Create test result
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        $testVMData = $allVMData
        ProvisionVMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        $superUser = "root"

        $myString = @"
# cd /root/
chmod +x perf_syscallbenchmark.sh
./perf_syscallbenchmark.sh &> syscallConsoleLogs.txt
. utils.sh
collect_VM_properties
"@

        Set-Content "$LogDir\StartSysCallBenchmark.sh" $myString
        RemoteCopy -uploadTo $testVMData.PublicIP -port $testVMData.SSHPort -files ".\$LogDir\StartSysCallBenchmark.sh" -username $superUser -password $password -upload
        RunLinuxCmd -ip $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -command "chmod +x *.sh" | Out-Null
        $testJob = RunLinuxCmd -ip $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -command "./StartSysCallBenchmark.sh" -RunInBackground
        #endregion

        #region MONITOR TEST
        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = RunLinuxCmd -ip $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -command "tail -1 syscallConsoleLogs.txt"
            LogMsg "Current Test Status : $currentStatus"
            WaitFor -seconds 20
        }

        $finalStatus = RunLinuxCmd -ip $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -command "cat state.txt"
        RemoteCopy -downloadFrom $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -download -downloadTo $LogDir -files "*.txt,*.log,*.csv"
        $testSummary = $null
        #endregion

        if ($finalStatus -imatch "TestFailed") {
            LogErr "Test failed. Last known status : $currentStatus."
            $testResult = "FAIL"
        }
        elseif ($finalStatus -imatch "TestAborted") {
            LogErr "Test Aborted. Last known status : $currentStatus."
            $testResult = "ABORTED"
        }
        elseif ($finalStatus -imatch "TestCompleted") {
            RemoteCopy -downloadFrom $testVMData.PublicIP -port $testVMData.SSHPort -username $superUser -password $password -download -downloadTo $LogDir -files "syscall-benchmark-*.tar.gz"
            LogMsg "Test Completed."
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
                $currentResult = Get_Syscall_Result_Object

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
                            $resultSummary +=  CreateResultSummary -testResult "$syscallResult : Completed" -metaData $metadata -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                            if ( $currentResult.test -imatch "bench_22_write_stdio") {
                                LogMsg "Syscall results parsing is Done..."
                                break
                            }
                            $currentResult = Get_Syscall_Result_Object
                        }
                        default {
                            continue
                        }
                    }
                }
                Set-Content -Value ($finalResult | Format-Table | Out-String) -Path "$LogDir\syscalResults.txt"
                Write-Host ($finalResult | Format-Table | Out-String)

                LogMsg "Uploading test results to Database.."
                $dataSource = $xmlConfig.config.$TestPlatform.database.server
                $user = $xmlConfig.config.$TestPlatform.database.user
                $password = $xmlConfig.config.$TestPlatform.database.password
                $database = $xmlConfig.config.$TestPlatform.database.dbname
                $dataTableName = $xmlConfig.config.$TestPlatform.database.dbtable
                $TestCaseName = $xmlConfig.config.$TestPlatform.database.testTag
                if ($dataSource -And $user -And $password -And $database -And $dataTableName) {
                    $GuestDistro    = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""}
                    if ($UseAzureResourceManager) {
                        $HostType   = "Azure-ARM"
                    } else {
                        $HostType   = "Azure"
                    }
                    $HostBy = ($xmlConfig.config.$TestPlatform.General.Location).Replace('"','')
                    $HostOS = Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version"| ForEach-Object{$_ -replace ",Host Version,",""}
                    $GuestOSType    = "Linux"
                    $GuestDistro    = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""}
                    $GuestSize = $testVMData.InstanceSize
                    $KernelVersion  = Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version"| ForEach-Object{$_ -replace ",Kernel version,",""}
                    $LisVersion  = Get-Content "$LogDir\VM_properties.csv" | Select-String "LIS Version"| ForEach-Object{$_ -replace ",LIS Version,",""}
                    $cpuInfo = Get-Content -Path $logFilePath | Select-Object -First 1
                    $connectionString = "Server=$dataSource;uid=$user; pwd=$password;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
                    $SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,GuestOSType,GuestDistro,GuestSize,KernelVersion,LISVersion,CPU,SyscallTest,CpuUsageAvgReal,CpuUsageAvgUser,CpuUsageAvgSystem) VALUES "
                    for ($i = 1; $i -lt $finalResult.Count; $i++) {
                        if ($finalResult[$i].test){
                            $SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$GuestOSType','$GuestDistro','$GuestSize','$KernelVersion','$LisVersion','$cpuInfo','$($finalResult[$i].test)',$($finalResult[$i].avgReal),$($finalResult[$i].avgUser),$($finalResult[$i].avgSystem)),"
                        } else {
                            continue
                        }
                    }
                    $SQLQuery = $SQLQuery.TrimEnd(',')
                    LogMsg $SQLQuery
                    $connection = New-Object System.Data.SqlClient.SqlConnection
                    $connection.ConnectionString = $connectionString
                    $connection.Open()
                    $command = $connection.CreateCommand()
                    $command.CommandText = $SQLQuery
                    $command.executenonquery() | Out-Null
                    $connection.Close()
                    LogMsg "Uploading test results to Database is done!!"
                } else {
                    LogMsg "Invalid database details. Failed to upload result to database!"
                }
            } catch {
                $ErrorMessage =  $_.Exception.Message
                $ErrorLine = $_.InvocationInfo.ScriptLineNumber
                LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
            }
        }
        elseif ($finalStatus -imatch "TestRunning") {
            LogMsg "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
            LogMsg "Contents of summary.log : $testSummary"
            $testResult = "PASS"
        }
        LogMsg "Test result : $testResult"
        LogMsg "Test Completed"
        $currentTestResult.TestSummary += CreateResultSummary -testResult $testResult -metaData "" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        $metaData = "SYSCALL RESULT"
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
