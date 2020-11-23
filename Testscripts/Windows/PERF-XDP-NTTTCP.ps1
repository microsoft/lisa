# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This script deploys the VM and Verifies there are no regression in Network Performance due
    to XDP by comparing ntttcp results.
#>

param([object] $AllVmData,
    [object] $CurrentTestData)

$iFaceName = "eth1"
$thresholdThroughput = 0.90

function Run_NTTTCP_PERF {
    $ResultDir = $args[0]
    Write-LogInfo "Starting ntttcp perf test"
    $testJob = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
        -username $user -password $password -command "./perf_ntttcp.sh &> ~/ntttcpConsoleLogs.txt" `
        -RunInBackground -runAsSudo
    while ((Get-Job -Id $testJob).State -eq "Running") {
        $currentStatus = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -command "tail -2 ~/ntttcpConsoleLogs.txt | head -1" -runAsSudo
        Write-LogInfo "Current Test Status: $currentStatus"
        Wait-Time -seconds 20
    }
    # Copy result
    Copy-RemoteFiles -downloadFrom $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
        -username $user -password $password -download `
        -downloadTo $ResultDir -files "~/ntttcp-tcp-test-logs/report.*" -runAsSudo
}

function Compare_NTTTCP_Result {
    $beforeDirPath = Join-Path -Path $args[0] -ChildPath 'report.csv'
    $afterDirPath = Join-Path -Path $args[1] -ChildPath 'report.csv'

    Write-LogInfo "Importing CSV from path $afterDirPath"
    $csvWithXDP = Import-Csv -Path $afterDirPath
    Write-LogInfo "Importing CSV from path $beforePath"
    $csvWithoutXDP = Import-Csv -Path $beforeDirPath
    $testFailedFlag = $false
    if ( ($csvWithXDP).Count -ne ($csvWithoutXDP).Count) {
        Throw "NTTTCP did not executed properly. Different number of lines in report.csv `
                Lines in Report with XDP: $($csvWithXDP.count) and Report without XDP: $($csvWithoutXDP.count)"
    }

    for ($itr = 0; $itr -lt ($csvWithXDP).Count; $itr++) {
        # Compare throughput
        Write-LogInfo "Throughput for $([math]::Pow(2,$itr)) connections"
        $thrWithoutXDP = $csvWithoutXDP[$itr].throughput_in_Gbps
        $thrWithtXDP = $csvWithXDP[$itr].throughput_in_Gbps
        $currentTestResult.TestSummary += New-ResultSummary -testResult $thrWithoutXDP -metaData "Without XDP Throughput $([math]::Pow(2,$itr)) connections" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        $currentTestResult.TestSummary += New-ResultSummary -testResult $thrWithtXDP -metaData "With XDP Throughput $([math]::Pow(2,$itr)) connections" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        $thresholdLimit = [math]::Floor([double]($thrWithoutXDP * $thresholdThroughput))
        if ($thrWithtXDP -lt $thresholdLimit) {
            Write-LogErr "Throughput With XDP running $ThrWithXDP is less than `
                threshold % of throughput without XDP $thrWithoutXDP"
            $testFailedFlag = $true
        }
        else {
            Write-LogInfo "Throughput with XDP running $ThrWithXDP is `
                greater than threshold % of throughput without XDP $thrWithoutXDPs"
        }

    }
    if ($testFailedFlag) {
        return $false
    }
    else {
        return $true
    }
}


function Create_Database_Result {

    $XDPLogDir = $args[0]
    $TestCaseName = $args[1]
    $LogContents = Get-Content -Path "$LogDir\$XDPLogDir\report.log"
    $TestDate = $(Get-Date -Format yyyy-MM-dd)
    $testType = "TCP"
    Write-LogInfo "Generating the performance data for database insertion with $XDPLogDir directory"
    for ($i = 1; $i -lt $LogContents.Count; $i++) {
        $Line = $LogContents[$i].Trim() -split '\s+'
        $resultMap = @{}
        $resultMap["TestCaseName"] = $TestCaseName
        $resultMap["TestDate"] = $TestDate
        $resultMap["HostType"] = $TestPlatform
        $resultMap["HostBy"] = $CurrentTestData.SetupConfig.TestLocation
        $resultMap["HostOS"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version" | ForEach-Object { $_ -replace ",Host Version,", "" })
        $resultMap["GuestOSType"] = "Linux"
        $resultMap["GuestDistro"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type" | ForEach-Object { $_ -replace ",OS type,", "" })
        $resultMap["GuestSize"] = $receiverVMData.InstanceSize
        $resultMap["KernelVersion"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version" | ForEach-Object { $_ -replace ",Kernel version,", "" })
        $resultMap["IPVersion"] = "IPv4"
        $resultMap["ProtocolType"] = $testType
        $resultMap["DataPath"] = $XDPLogDir
        $resultMap["NumberOfConnections"] = $($Line[0])
        $resultMap["Throughput_Gbps"] = $($Line[1])
        $resultMap["SenderCyclesPerByte"] = $($Line[2])
        $resultMap["ReceiverCyclesPerByte"] = $($Line[3])
        $resultMap["Latency_ms"] = $($Line[4])
        $resultMap["TXpackets"] = $($Line[5])
        $resultMap["RXpackets"] = $($Line[6])
        $resultMap["PktsInterrupts"] = $($Line[7])
        $resultMap["ConnectionsCreatedTime"] = $($Line[8])
        $resultMap["RetransSegments"] = $($Line[9])
        $currentTestResult.TestResultData += $resultMap
    }
}

function Main {
    try {
        $noReceiver = $true
        $noSender = $true
        foreach ($vmData in $allVMData) {
            if ($vmData.RoleName -imatch "receiver") {
                $receiverVMData = $vmData
                $noReceiver = $false
            }
            elseif ($vmData.RoleName -imatch "sender") {
                $noSender = $false
                $senderVMData = $vmData
            }
        }
        if ($noReceiver) {
            Throw "No Receiver VM defined. Aborting Test."
        }
        if ($noSender) {
            Throw "No Sender VM defined. Aborting Test."
        }

        #CONFIGURE VM Details
        Write-LogInfo "CLIENT VM details :"
        Write-LogInfo "  RoleName : $($receiverVMData.RoleName)"
        Write-LogInfo "  Public IP : $($receiverVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($receiverVMData.SSHPort)"
        Write-LogInfo "  Internal IP : $($receiverVMData.InternalIP)"
        Write-LogInfo "SERVER VM details :"
        Write-LogInfo "  RoleName : $($senderVMData.RoleName)"
        Write-LogInfo "  Public IP : $($senderVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($senderVMData.SSHPort)"
        Write-LogInfo "  Internal IP : $($senderVMData.InternalIP)"

        # PROVISION VMS FOR LISA WILL ENABLE ROOT USER AND WILL MAKE ENABLE PASSWORDLESS AUTHENTICATION ACROSS ALL VMS.
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

        Write-LogInfo "Generating constants.sh ..."
        $constantsFile = "$LogDir\constants.sh"
        Set-Content -Value "#Generated by Azure Automation." -Path $constantsFile
        Add-Content -Value "ip=$($receiverVMData.InternalIP)" -Path $constantsFile
        Add-Content -Value "client=$($receiverVMData.InternalIP)" -Path $constantsFile
        # Giving server IP as secondary to run NTTTCP on secondary NIC.
        Add-Content -Value "server=$($senderVMData.SecondInternalIP)" -Path $constantsFile
        Add-Content -Value "nicName=$iFaceName" -Path $constantsFile
        foreach ($param in $currentTestData.TestParameters.param) {
            Add-Content -Value "$param" -Path $constantsFile
        }
        Write-LogInfo "constants.sh created successfully..."
        Write-LogInfo (Get-Content -Path $constantsFile)
        # Start XDP Installation
        $installXDPCommand = @"
bash ./XDPDumpSetup.sh 2>&1 > ~/xdpConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
        Set-Content "$LogDir\StartXDPSetup.sh" $installXDPCommand
        Copy-RemoteFiles -uploadTo $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -files "$constantsFile,$LogDir\StartXDPSetup.sh" `
            -username $user -password $password -upload -runAsSudo
        Copy-RemoteFiles -uploadTo $senderVMData.PublicIP -port $senderVMData.SSHPort `
            -files "$constantsFile" `
            -username $user -password $password -upload -runAsSudo
        $testJob = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -command "bash ./StartXDPSetup.sh" `
            -RunInBackground -runAsSudo
        # Terminate process if ran more than 5 mins
        # TODO: Check max installation time for other distros when added
        $timer = 0
        while ($testJob -and ((Get-Job -Id $testJob).State -eq "Running")) {
            $currentStatus = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
                -username $user -password $password -command "tail -2 ~/xdpConsoleLogs.txt | head -1" -runAsSudo
            Write-LogInfo "Current Test Status: $currentStatus"
            Wait-Time -seconds 20
            $timer += 1
            if ($timer -gt 15) {
                Throw "XDPSetup did not stop after 5 mins. Please check xdpConsoleLogs."
            }
        }

        $currentState = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -command "cat state.txt" -runAsSudo
        if ($currentState -imatch "Completed") {
            # Start PERF test without XDP
            $ResultDir = "$LogDir\WithoutXDP"
            New-Item -Path $ResultDir -ItemType Directory -Force | Out-Null
            Run_NTTTCP_PERF $ResultDir

            # Start XDPDump on client
            $xdp_build = "cd /root/bpf-samples/xdpdump && make clean &&  CFLAGS='-D __PERF__ -I../libbpf/src/root/usr/include' make"
            $testJobXDP = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user `
                -password $password -command $xdp_build -runAsSudo
            $xdp_command = "cd /root/bpf-samples/xdpdump && ./xdpdump -i $iFaceName > ~/xdpdumpoutPERF.txt"
            $testJobXDP = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user `
                -password $password -command $xdp_command -RunInBackground -runAsSudo
            Write-LogInfo "XDP Dump process started with id: $testJobXDP"

            # Run server client of ntttcp
            $ResultDirXDP = "$LogDir\WithXDP"
            New-Item -Path $ResultDirXDP -ItemType Directory -Force | Out-Null
            Run_NTTTCP_PERF $ResultDirXDP
            # collect and compare result
            if (Compare_NTTTCP_Result $ResultDir $ResultDirXDP) {
                Write-LogInfo "Test Completed"
                $testResult = "PASS"
            }
            else {
                Write-LogErr "Test failed. Throughput result below threshold."
                $testResult = "FAIL"
            }
        }
        elseif ($currentState -imatch "TestAborted") {
            Write-LogErr "Test Aborted. Last known status: $currentStatus."
            $testResult = "ABORTED"
        }
        elseif ($currentState -imatch "TestSkipped") {
            Write-LogErr "Test Skipped. Last known status: $currentStatus."
            $testResult = "SKIPPED"
        }
        elseif ($currentState -imatch "TestFailed") {
            Write-LogErr "Test failed. Last known status: $currentStatus."
            $testResult = "FAIL"
        }
        else {
            Write-LogErr "Test execution is not successful, check test logs in VM. Last known status: $currentStatus."
            $testResult = "ABORTED"
        }
        Copy-RemoteFiles -downloadFrom $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -download `
            -downloadTo $LogDir -files "*.csv, *.txt, *.log" -runAsSudo

        if ($testResult -eq "PASS") {
            $TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
            if (!$TestCaseName) {
                $TestCaseName = $CurrentTestData.testName
            }
            Create_Database_Result "WithXDP" $TestCaseName
            Create_Database_Result "WithoutXDP" $TestCaseName
        }
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    Write-LogInfo "Test result: $testResult"
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main
