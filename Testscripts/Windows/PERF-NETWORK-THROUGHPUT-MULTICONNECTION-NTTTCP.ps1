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
        $noClient = $true
        $noServer = $true
        $clientMachines = @()
        $clientIPs = ""
        $numberOfReceivers = 0
        $numberOfSenders = 0
        # role-0 vm is considered as the server-vm
        # role-1 to role-8 vm is considered as the client-vm-01 to client-vm-08
        foreach ($vmData in $allVMData) {
            if ($vmData.RoleName -imatch "server" -or $vmData.RoleName -imatch "role-0") {
                $serverVMData = $VmData
                $noServer = $false
                $numberOfReceivers++
            } elseif ($vmData.RoleName -imatch "client" -or $vmData.RoleName -imatch "role-1") {
                $clientMachines += $VmData
                $noClient = $false
                if ($clientIPs) {
                    $clientIPs += "," + $vmData.InternalIP
                } else {
                    $clientIPs = $vmData.InternalIP
                }
                $numberOfSenders++
            }
        }
        if ($noClient -or $noServer) {
            Throw "Client or Server VM not defined. Be sure that the SetupType has 2 VMs defined"
        }
        Write-LogInfo "SERVER VM details :"
        Write-LogInfo "  RoleName : $($serverVMData.RoleName)"
        Write-LogInfo "  Public IP : $($serverVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($serverVMData.SSHPort)"
        $i = 1
        foreach ($clientVMData in $clientMachines) {
            Write-LogInfo "CLIENT VM #$i details :"
            Write-LogInfo "  RoleName : $($clientVMData.RoleName)"
            Write-LogInfo "  Public IP : $($clientVMData.PublicIP)"
            Write-LogInfo "  SSH Port : $($clientVMData.SSHPort)"
            $i += 1
        }

        # PROVISION VMS FOR LISA WILL ENABLE ROOT USER AND WILL MAKE ENABLE PASSWORDLESS AUTHENTICATION ACROSS ALL VMS IN SAME HOSTED SERVICE.
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        #endregion

        Write-LogInfo "Getting Systemd Version."
        $getSystemdVersion = "systemctl --version | head -n1 | awk '{ print `$NF }'"
        $systemdVersion = (Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort `
            -username $user -password $password -command $getSystemdVersion ).Trim()
        Write-LogInfo "Systemd Version is $systemdVersion. Set Systemd user config file..."

        if (($systemdVersion -as [int]) -ge 239) {
            # In systemd v239 and later, the user default is set via TasksMax= in /usr/lib/systemd/system/user-.slice.d/10-defaults.conf
            $setSystemdConfig = "sed -i 's/TasksMax.*/TasksMax=122880/' /usr/lib/systemd/system/user-.slice.d/10-defaults.conf"
        } else {
            # Add a new line configuration in systemd logind.conf. UserTasksMax sets the maximum number of OS tasks each user may run concurrently.
            $setSystemdConfig = "sed -i '`$aUserTasksMax=122880' /etc/systemd/logind.conf"
        }
        Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user `
                    -password $password -command $setSystemdConfig -runAsSudo | Out-Null

        # Restart VM to apply systemd setting
        if (-not $TestProvider.RestartAllDeployments($allVMData)) {
            Write-LogErr "Unable to connect to VM after restart!"
            $currentTestResult.TestResult = "ABORTED"
            return $currentTestResult
        }

        Write-LogInfo "Getting Active NIC Name."
        if ($TestPlatform -eq "HyperV") {
            $clientNicName = Get-GuestInterfaceByVSwitch $TestParams.PERF_NIC $clientVMData.RoleName `
                $clientVMData.HypervHost $user $clientVMData.PublicIP $password $clientVMData.SSHPort
            $serverNicName = Get-GuestInterfaceByVSwitch $TestParams.PERF_NIC $serverVMData.RoleName `
                $serverVMData.HypervHost $user $serverVMData.PublicIP $password $serverVMData.SSHPort
        } else {
            $getNicCmd = ". ./utils.sh &> /dev/null && get_active_nic_name"
            $clientNicName = (Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort `
                -username "root" -password $password -command $getNicCmd).Trim()
            $serverNicName = (Run-LinuxCmd -ip $serverVMData.PublicIP -port $serverVMData.SSHPort `
                -username "root" -password $password -command $getNicCmd).Trim()
        }

        if ($serverNicName -eq $clientNicName) {
            $nicName = $clientNicName
        } else {
            Throw "Server and client SRIOV NICs are not same."
        }
        if ($currentTestData.SetupConfig.Networking -imatch "SRIOV") {
            $DataPath = "SRIOV"
        } else {
            $DataPath = "Synthetic"
        }
        Write-LogInfo "CLIENT $DataPath NIC: $clientNicName"
        Write-LogInfo "SERVER $DataPath NIC: $serverNicName"

        Write-LogInfo "Generating constants.sh ..."
        $constantsFile = "$LogDir\constants.sh"
        Set-Content -Value "#Generated by LISAv2 Automation" -Path $constantsFile
        Add-Content -Value "server=$($serverVMData.InternalIP)" -Path $constantsFile
        Add-Content -Value "client=`"$clientIPs`"" -Path $constantsFile
        Add-Content -Value "nicName=$nicName" -Path $constantsFile
        foreach ($param in $currentTestData.TestParameters.param) {
            Add-Content -Value "$param" -Path $constantsFile
            if ($param -imatch "bufferLength=") {
                $testBuffer = $($param.Replace('bufferLength=','')/1024)
            }
        }
        Write-LogInfo "constants.sh created successfully..."
        Write-LogInfo (Get-Content -Path $constantsFile)

        #region EXECUTE TEST
        $myString = @"
cd /root/
./perf_ntttcp.sh &> ntttcpConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
        Set-Content "$LogDir\StartNtttcpTest.sh" $myString
        Copy-RemoteFiles -uploadTo $clientVMData.PublicIP -port $clientVMData.SSHPort -files "$constantsFile,$LogDir\StartNtttcpTest.sh" -username "root" -password $password -upload
        Copy-RemoteFiles -uploadTo $clientVMData.PublicIP -port $clientVMData.SSHPort -files $currentTestData.files -username "root" -password $password -upload

        Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "chmod +x *.sh" | Out-Null
        $testJob = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "/root/StartNtttcpTest.sh" -RunInBackground
        #endregion

        #region MONITOR TEST
        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "tail -2 ntttcpConsoleLogs.txt | head -1" -ignoreLinuxExitCode:$true -maxRetryCount 60
            Write-LogInfo "Current Test Status : $currentStatus."
            Write-LogInfo "Sleep for 1 min."
            Wait-Time -seconds 60
        }
        $finalStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "cat /root/state.txt"
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "/root/ntttcpConsoleLogs.txt"
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "ntttcp-*.log"
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "report.log, report.csv"
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "VM_properties.csv"

        $testSummary = $null
        $uploadResults = $true
        $ntttcpReportLog = Get-Content -Path "$LogDir\report.log"

        $ntttcpResults = @()
        $ntttcpResultObject = @{
            "meta_data" = @{
                "connections" = $null;
                "type" = $null;
            };
            "tx_throughput_gbps" = $null;
        }

        foreach ($line in $ntttcpReportLog) {
            if ($line -imatch "test_connections") {
                continue;
            }
            try {
                $currentNtttcpResultObject = $ntttcpResultObject.Clone()
                $currentNtttcpResultObject["meta_data"] = $ntttcpResultObject["meta_data"].Clone()

                if ($CurrentTestData.testName -imatch "udp") {
                    $testType = "UDP"
                    $test_connections = ($line.Trim() -Replace " +"," ").Split(" ")[0]
                    $tx_throughput_gbps = ($line.Trim() -Replace " +"," ").Split(" ")[1]
                    $rx_throughput_gbps = ($line.Trim() -Replace " +"," ").Split(" ")[2]
                    $datagram_loss = ($line.Trim() -Replace " +"," ").Split(" ")[3]
                    $connResult = "tx_throughput=$tx_throughput_gbps`Gbps rx_throughput=$rx_throughput_gbps`Gbps datagram_loss=$datagram_loss"
                    $currentNtttcpResultObject["meta_data"]["connections"] = $test_connections
                    $currentNtttcpResultObject["meta_data"]["type"] = $testType
                    $currentNtttcpResultObject["rx_txhroughput_gbps"] = $rx_throughput_gbps
                    $currentNtttcpResultObject["tx_throughput_gbps"] = $tx_throughput_gbps
                    $currentNtttcpResultObject["datagram_loss"] = $datagram_loss
                } else {
                    $testType = "TCP"
                    $test_connections = ($line.Trim() -Replace " +"," ").Split(" ")[0]
                    $throughput_gbps = ($line.Trim() -Replace " +"," ").Split(" ")[1]
                    $cycles_per_byte_sender = ($line.Trim() -Replace " +"," ").Split(" ")[2]
                    $cycles_per_byte_receiver = ($line.Trim() -Replace " +"," ").Split(" ")[3]
                    $average_tcp_latency = ($line.Trim() -Replace " +"," ").Split(" ")[4]
                    $txpackets_sender = ($line.Trim() -Replace " +"," ").Split(" ")[5]
                    $rxpackets_sender = ($line.Trim() -Replace " +"," ").Split(" ")[6]
                    $pktsInterrupt_sender = ($line.Trim() -Replace " +"," ").Split(" ")[7]
                    $concreatedtime = ($line.Trim() -Replace " +"," ").Split(" ")[8]
                    $retrans_segs = ($line.Trim() -Replace " +"," ").Split(" ")[9]
                    $connResult = "throughput=$throughput_gbps`Gbps cyclesPerByte_sender=$cycles_per_byte_sender cyclesPerByte_receiver=$cycles_per_byte_receiver Avg_TCP_lat=$average_tcp_latency pktsPerInterrupt=$pktsInterrupt_sender conCreatedTime=$concreatedtime retransSegs=$retrans_segs"
                    $currentNtttcpResultObject["meta_data"]["connections"] = $test_connections
                    $currentNtttcpResultObject["meta_data"]["type"] = $testType
                    $currentNtttcpResultObject["cycles_per_byte_sender"] = $cycles_per_byte_sender
                    $currentNtttcpResultObject["cycles_per_byte_receiver"] = $cycles_per_byte_receiver
                    $currentNtttcpResultObject["tx_throughput_gbps"] = $throughput_gbps
                    $currentNtttcpResultObject["average_tcp_latency"] = $average_tcp_latency
                    $currentNtttcpResultObject["txpackets_sender"] = $txpackets_sender
                    $currentNtttcpResultObject["rxpackets_sender"] = $rxpackets_sender
                    $currentNtttcpResultObject["pktsInterrupt_sender"] = $pktsInterrupt_sender
                    $currentNtttcpResultObject["concreatedtime"] = $concreatedtime
                    $currentNtttcpResultObject["retrans_segs"] = $retrans_segs
                }
                $ntttcpResults += $currentNtttcpResultObject
                $metadata = "Connections=$test_connections"
                $currentTestResult.TestSummary += New-ResultSummary -testResult $connResult -metaData $metaData -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                if (([float]$throughput_gbps -eq 0 -and $testType -eq "tcp") -or ($testType -eq "udp" -and ([float]$rx_throughput_gbps -eq 0 -or [float]$tx_throughput_gbps -eq 0))) {
                    $uploadResults = $false
                    $testResult = "FAIL"
                }
            } catch {
                $currentTestResult.TestSummary += New-ResultSummary -testResult "Error in parsing logs." -metaData "NTTTCP" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            }
        }
        #endregion
        $ntttcpResultsFile = "${LogDir}\$($currentTestData.testName)_perf_results.json"
        $ntttcpResults | ConvertTo-Json | Out-File $ntttcpResultsFile -Encoding "ascii"
        Write-LogInfo "Perf results in json format saved at: ${ntttcpResultsFile}"

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
            Write-LogInfo "Contents of summary.log : $testSummary"
            $testResult = "PASS"
        }

        $ntttcpDataCsv = Import-Csv -Path $LogDir\report.csv
        Write-LogInfo ("`n**************************************************************************`n"+$CurrentTestData.testName+" RESULTS...`n**************************************************************************")
        Write-Host ($ntttcpDataCsv | Format-Table * | Out-String)

        $LogContents = Get-Content -Path "$LogDir\report.log"
        $TestDate = $(Get-Date -Format yyyy-MM-dd)
        if ($testResult -eq "PASS") {
            $TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
            if (!$TestCaseName) {
                $TestCaseName = $CurrentTestData.testName
            }
            Write-LogInfo "Generating the performance data for database insertion"
            for ($i = 1; $i -lt $LogContents.Count; $i++) {
                $Line = $LogContents[$i].Trim() -split '\s+'
                $resultMap = @{}
                $resultMap["TestCaseName"] = $TestCaseName
                $resultMap["TestDate"] = $TestDate
                $resultMap["HostType"] = $TestPlatform
                $resultMap["HostBy"] = $CurrentTestData.SetupConfig.TestLocation
                $resultMap["HostOS"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version"| ForEach-Object{$_ -replace ",Host Version,",""})
                $resultMap["GuestOSType"] = "Linux"
                $resultMap["GuestDistro"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""})
                $resultMap["GuestSize"] = $clientVMData.InstanceSize
                $resultMap["KernelVersion"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version"| ForEach-Object{$_ -replace ",Kernel version,",""})
                $resultMap["IPVersion"] = "IPv4"
                $resultMap["ProtocolType"] = $testType
                $resultMap["DataPath"] = $DataPath
                $resultMap["NumberOfConnections"] = $($Line[0])
                if ($testType -imatch "UDP") {
                    $resultMap["SendBufSize_KBytes"] = $testBuffer
                    $resultMap["TxThroughput_Gbps"] = $($Line[1])
                    $resultMap["RxThroughput_Gbps"] = $($Line[2])
                    $resultMap["DatagramLoss"] = $($Line[3])
                } else {
                    $resultMap["Throughput_Gbps"] = $($Line[1])
                    $resultMap["SenderCyclesPerByte"] = $($Line[2])
                    $resultMap["ReceiverCyclesPerByte"] = $($Line[3])
                    $resultMap["Latency_ms"] = $($Line[4])
                    $resultMap["TXpackets"] = $($Line[5])
                    $resultMap["RXpackets"] = $($Line[6])
                    $resultMap["PktsInterrupts"] = $($Line[7])
                    $resultMap["ConnectionsCreatedTime"] = $($Line[8])
                    $resultMap["RetransSegments"] = $($Line[9])
                }
                if ($TestPlatform -eq "Azure") {
                    $resultMap["NumberOfReceivers"] = $numberOfReceivers
                    $resultMap["NumberOfSenders"] = $numberOfSenders
                }
                $currentTestResult.TestResultData += $resultMap
            }
        }
        Write-LogInfo "Test result : $testResult"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        $metaData = "NTTTCP RESULT"
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVMData $AllVmData
