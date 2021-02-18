# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param(
    [String] $TestParams,
    [object] $AllVmData,
    [object] $CurrentTestData
)

function Write-TestInformation {
    param(
        $clientVMData,
        $serverVMData
    )

    Write-LogInfo "CLIENT VM details :"
    Write-LogInfo "  RoleName  : $($clientVMData.RoleName)"
    Write-LogInfo "  Public IP : $($clientVMData.PublicIP)"
    Write-LogInfo "  SSH Port  : $($clientVMData.SSHPort)"
    Write-LogInfo "  Location  : $($clientVMData.Location)"
    Write-LogInfo "SERVER VM details :"
    Write-LogInfo "  RoleName  : $($serverVMData.RoleName)"
    Write-LogInfo "  Public IP : $($serverVMData.PublicIP)"
    Write-LogInfo "  SSH Port  : $($serverVMData.SSHPort)"
    Write-LogInfo "  Location  : $($serverVMData.Location)"
}

function Get-Iperf3PerformanceResults {
    param(
        $BufferLengths,
        $Iperf3ResultDir,
        $ProtocolType = "TCP",
        $IPVersion = "IPv4",
        $Connections = "1"
    )

    $Iperf3Results = @()
    $iperfResultObject = @{
        "meta_data" = @{
            "buffer_length" = $null;
        };
        "rx_throughput_gbps" = $null;
        "tx_throughput_gbps" = $null;
        "congestion_windowsize_kb" = $null;
        "retransmitted_segments" = $null;
    }

    foreach ($bufferLength in $BufferLengths) {
        # remove extra warnings from the iperf results
        $fileFormat = "{0}\iperf-{1}-{2}-{3}-buffer-{4}-conn-{5}-instance-1.txt"
        $serverContent = Get-Content ($fileFormat -f @($Iperf3ResultDir, "server", $ProtocolType, $IPVersion, $bufferLength, $Connections))
        while(!$serverContent[0].ToString().Contains("{")) {
            $serverContent = $serverContent[1..($serverContent.Length-1)]
        }
        $clientContent = Get-Content ($fileFormat -f @($Iperf3ResultDir, "client", $ProtocolType, $IPVersion, $bufferLength, $Connections))
        while(!$clientContent[0].ToString().Contains("{")) {
            $clientContent = $clientContent[1..($clientContent.Length-1)]
        }

        $serverJson = ConvertFrom-Json -InputObject ([string]($serverContent))
        $clientJson = ConvertFrom-Json -InputObject ([string]($clientContent))

        $RxThroughput_Gbps = [math]::Round($serverJson.end.sum_received.bits_per_second/1000000000,2)
        $TxThroughput_Gbps = [math]::Round($clientJson.end.sum_received.bits_per_second/1000000000,2)
        $RetransmittedSegments = $clientJson.end.streams.sender.retransmits
        $CongestionWindowSize_KB_Total = 0
        foreach ($interval in $clientJson.intervals) {
            $CongestionWindowSize_KB_Total += $interval.streams.snd_cwnd
        }
        $CongestionWindowSize_KB = [math]::Round($CongestionWindowSize_KB_Total / $clientJson.intervals.Count / 1024 )

        $currentIperfResultObject = $iperfResultObject.Clone()
        $currentIperfResultObject["meta_data"] = $iperfResultObject["meta_data"].Clone()
        $currentIperfResultObject["meta_data"]["buffer_length"] = $bufferLength
        $currentIperfResultObject["rx_throughput_gbps"] = $RxThroughput_Gbps
        $currentIperfResultObject["tx_throughput_gbps"] = $TxThroughput_Gbps
        $currentIperfResultObject["congestion_windowsize_kb"] = $CongestionWindowSize_KB
        $currentIperfResultObject["retransmitted_segments"] = $RetransmittedSegments
        $iperfResults = "tx_throughput=$TxThroughput_Gbps`Gbps rx_throughput=$RxThroughput_Gbps`Gbps retransmitted_segments=$RetransmittedSegments congestion_windowsize_kb=$CongestionWindowSize_KB"

        $Iperf3Results += $currentIperfResultObject
        $Metadata = "BufferLengths=$bufferLength"
        $currentTestResult.TestSummary += New-ResultSummary -testResult $iperfResults -metaData $Metadata -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
    }

    return $Iperf3Results
}

function Consume-Iperf3Results {
    param(
        $Iperf3Results,
        $DataPath,
        $IPVersion,
        $ClientVMData,
        $currentTestData,
        $currentTestResult
    )

    $TestDate = Get-Date -Format 'yyyy/MM/dd HH:mm:ss'
    $GuestDistro = cat "$LogDir\VM_properties.csv" | Select-String "OS type"| %{$_ -replace ",OS type,",""}
    $HostOS = cat "$LogDir\VM_properties.csv" | Select-String "Host Version"| %{$_ -replace ",Host Version,",""}
    $GuestOSType = "Linux"
    $GuestDistro = cat "$LogDir\VM_properties.csv" | Select-String "OS type"| %{$_ -replace ",OS type,",""}
    $GuestSize = $ClientVMData.InstanceSize
    $KernelVersion = cat "$LogDir\VM_properties.csv" | Select-String "Kernel version"| %{$_ -replace ",Kernel version,",""}
    if ($KernelVersion.Length -ge 28) {
        $KernelVersion = $KernelVersion.Trim().Substring(0,28)
    }
    $ProtocolType = "TCP"

    foreach ($perfResult in $Iperf3Results) {
        $resultMap = @{}
        $resultMap["TestCaseName"] = $TestCaseName
        $resultMap["DataPath"] = $DataPath
        $resultMap["TestDate"] = $TestDate
        $resultMap["HostBy"] = $CurrentTestData.SetupConfig.TestLocation
        $resultMap["HostOS"] = $HostOS
        $resultMap["HostType"] = $TestPlatform
        $resultMap["GuestSize"] = $GuestSize
        $resultMap["GuestOSType"] = $GuestOSType
        $resultMap["GuestDistro"] = $GuestDistro
        $resultMap["KernelVersion"] = $KernelVersion
        $resultMap["IPVersion"] = $IPVersion
        $resultMap["ProtocolType"] = $ProtocolType
        $resultMap["BufferSize_Bytes"] = $perfResult["meta_data"]["buffer_length"]
        $resultMap["RxThroughput_Gbps"] = $perfResult["rx_throughput_gbps"]
        $resultMap["TxThroughput_Gbps"] = $perfResult["tx_throughput_gbps"]
        $resultMap["RetransmittedSegments"] = $perfResult["retransmitted_segments"]
        $resultMap["CongestionWindowSize_KB"] = $perfResult["congestion_windowsize_kb"]

        $currentTestResult.TestResultData += $resultMap
    }
}


function Main {
    param (
        $TestParams, $AllVmData, $CurrentTestData, $TestProvider
    )
    $resultArr = @()

    try {
	    $currentTestResult = Create-TestResultObject
        # Validate test setup
        $clientVMExists = $false
        $serverVMExists = $false
        # role-0 vm is considered as the client-vm
        # role-1 vm is considered as the server-vm
        foreach ($vmData in $allVMData) {
            if ($vmData.RoleName -imatch "role-0") {
                $clientVMData = $vmData
                $clientVMExists = $true
            }
            elseif ($vmData.RoleName -imatch "role-1") {
                $serverVMData = $vmData
                $serverVMExists = $true
            }
        }
        if (!$clientVMExists -or !$serverVMExists) {
            Throw "Client or Server VM not present. Make sure that the SetupType has 2 VMs defined."
        }

        Write-TestInformation $clientVMData $serverVMData
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

        if ($currentTestData.SetupConfig.Networking -imatch "SRIOV") {
            $DataPath = "SRIOV"
        } else {
            $DataPath = "Synthetic"
        }
        Write-LogInfo "Getting ${DataPath} NIC Name."
        if ($TestPlatform -eq "Azure") {
            $getNicCmd = ". ./utils.sh &> /dev/null && get_active_nic_name"
            $clientNicName = (Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort `
                -username "root" -password $password -command $getNicCmd).Trim()
            $serverNicName = (Run-LinuxCmd -ip $serverVMData.PublicIP -port $serverVMData.SSHPort `
                -username "root" -password $password -command $getNicCmd).Trim()
        } elseif ($TestPlatform -eq "HyperV") {
            $clientNicName = Get-GuestInterfaceByVSwitch $TestParams.PERF_NIC $clientVMData.RoleName `
                $clientVMData.HypervHost $user $clientVMData.PublicIP $password $clientVMData.SSHPort
            $serverNicName = Get-GuestInterfaceByVSwitch $TestParams.PERF_NIC $serverVMData.RoleName `
                $serverVMData.HypervHost $user $serverVMData.PublicIP $password $serverVMData.SSHPort
        } else {
            Throw "Test platform ${TestPlatform} not supported."
        }
        Write-LogInfo "CLIENT $DataPath NIC: $clientNicName"
        Write-LogInfo "SERVER $DataPath NIC: $serverNicName"
        if ( $serverNicName -eq $clientNicName) {
            Write-LogInfo "Server and client SRIOV NICs are the same."
        } else {
            Throw "Server and client SRIOV NICs are not the same."
        }

        # region GenerateConstants file
        $constantsFile = "$LogDir\constants.sh"
        Set-Content -Value "#Generated by LISAv2 Automation" -Path $constantsFile
        if ($clientVMData.PublicIP -eq $serverVMData.PublicIP) {
            Add-Content -Value "server=$($serverVMData.InternalIP)" -Path $constantsFile
            Add-Content -Value "client=$($clientVMData.InternalIP)" -Path $constantsFile
        } else {
            Add-Content -Value "server=$($serverVMData.PublicIP)" -Path $constantsFile
            Add-Content -Value "client=$($clientVMData.PublicIP)" -Path $constantsFile
        }
        foreach ($param in $currentTestData.TestParameters.param) {
            Add-Content -Value "$param" -Path $constantsFile
            if ($param -imatch "bufferLengths=") {
                $bufferLengths= $param.Replace("bufferLengths=(","").Replace(")","").Split(" ")
            }
            if ( $param -imatch "IPversion" ) {
                if ( $param -imatch "IPversion=6" ) {
                    $IPVersion = "IPv6"
                    Add-Content -Value "serverIpv6=$($serverVMData.PublicIPv6)" -Path $constantsFile
                    Add-Content -Value "clientIpv6=$($clientVMData.PublicIPv6)" -Path $constantsFile
                } else {
                    $IPVersion = "IPv4"
                }
            }
        }
        Write-LogInfo "constants.sh created successfully..."
        Write-LogInfo (Get-Content -Path $constantsFile)
        #endregion

        #region EXECUTE TEST
        $runIperfCmd = @"
cd /root/
./perf_iperf3.sh &> iperf3tcpConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
        Set-Content "$LogDir\Startiperf3tcpTest.sh" $runIperfCmd
        Copy-RemoteFiles -uploadTo $clientVMData.PublicIP -port $clientVMData.SSHPort -files "$constantsFile,$LogDir\Startiperf3tcpTest.sh" -username "root" -password $password -upload
        $null = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "chmod +x *.sh"
        $testJob = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "/root/Startiperf3tcpTest.sh" -RunInBackground
        #endregion

        #region MONITOR TEST
        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "tail -1 iperf3tcpConsoleLogs.txt"
            Write-LogInfo "Current Test Status: $currentStatus"
            Wait-Time -seconds 20
        }

        $finalStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -command "cat /root/state.txt"
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "/root/iperf3tcpConsoleLogs.txt"
        $iperf3LogDir = "$LogDir\iperf3Data"
        New-Item -itemtype directory -path $iperf3LogDir -Force -ErrorAction SilentlyContinue | Out-Null
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $iperf3LogDir -files "iperf-client-tcp*"
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $iperf3LogDir -files "iperf-server-tcp*"
        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "VM_properties.csv"

        if ($finalStatus -imatch "TestFailed") {
            Write-LogErr "Test failed. Last known status : $currentStatus."
            $testResult = "FAIL"
        } elseif ($finalStatus -imatch "TestAborted") {
            Write-LogErr "Test Aborted. Last known status : $currentStatus."
            $testResult = "ABORTED"
        } elseif ($finalStatus -imatch "TestCompleted") {
            Write-LogInfo "Test Completed."
            $testResult = "PASS"
            $iperf3Results = Get-Iperf3PerformanceResults -BufferLengths $bufferLengths `
                -Iperf3ResultDir $iperf3LogDir -IPVersion $IPVersion
            $iperf3ResutsFile = "${LogDir}\$($currentTestData.testName)_perf_results.json"
            $iperf3Results | ConvertTo-Json | Out-File $iperf3ResutsFile -Encoding "ascii"
            Write-LogInfo "Perf results in json format saved at: ${iperf3ResutsFile}"
            Consume-Iperf3Results -Iperf3Results $iperf3Results -DataPath $DataPath -IPVersion $IPVersion `
                -ClientVMData $clientVMData -currentTestData $currentTestData -currentTestResult $currentTestResult
        } elseif ($finalStatus -imatch "TestRunning") {
            Write-LogInfo "Powershell background job is completed but VM is reporting that test is still running. Please check $LogDir\ConsoleLogs.txt"
            $testResult = "FAIL"
        }
        Write-LogInfo "Test result: $testResult"
    } catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
        $ErrorMessage = $_.Exception.Message
        Write-LogErr "EXCEPTION: $ErrorMessage"
        Write-LogErr "Source: Line $line in script $script_name."
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVmData $AllVmData -CurrentTestData $CurrentTestData
