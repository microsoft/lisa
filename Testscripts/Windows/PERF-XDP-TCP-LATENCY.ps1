# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This script deploys the VM and verifies there are no regression in Network Latency caused
    by XDP. We achieve this by comparing lagscope results.
#>

param([object] $AllVmData,
    [object] $CurrentTestData)

$iFaceName = "eth1"
# Threshold value (40%) is calculated by analyzing 10 samples of latency values with and w/o XDP
$thresholdValue = 1.4

function Run_Lagscope_PERF {
    $ResultDir = $args[0]
    Write-LogInfo "Starting lagscope perf test"
    $testJob = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
        -username $user -password $password -command "./perf_lagscope.sh &> ~/lagscopeConsoleLogs.txt" `
        -RunInBackground -runAsSudo
    while ((Get-Job -Id $testJob).State -eq "Running") {
        $currentStatus = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -command "tail -2 ~/lagscopeConsoleLogs.txt | head -1" -runAsSudo
        Write-LogInfo "Current Test Status: $currentStatus"
        Wait-Time -seconds 20
    }
    # Copy result
    Copy-RemoteFiles -downloadFrom $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
        -username $user -password $password -download `
        -downloadTo $ResultDir -files "/tmp/lagscope-n*.txt" -runAsSudo
}

function Compare_Result {

    Write-LogInfo "Comparing lagscope results"
    $beforeDirPath = Join-Path -Path $args[0] -ChildPath "lagscope-n*-output.txt"
    $afterDirPath = Join-Path -Path $args[1] -ChildPath "lagscope-n*-output.txt"
    $avgLatency = 'default'
    $avgLatencyXDP = 'default'
    try {
        $matchLine = (Select-String -Path $beforeDirPath -Pattern "Average").Line
        $avgLatency = $matchLine.Split(",").Split("=").Trim().Replace("us", "")[5]
        $avgLatency = $avgLatency / 1
        $matchLineXDP = (Select-String -Path $afterDirPath -Pattern "Average").Line
        $avgLatencyXDP = $matchLineXDP.Split(",").Split("=").Trim().Replace("us", "")[5]
        $avgLatencyXDP = $avgLatencyXDP / 1

        $currentTestResult.TestSummary += New-ResultSummary -testResult $avgLatency -metaData "Without XDP Average Latency" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        $currentTestResult.TestSummary += New-ResultSummary -testResult $avgLatencyXDP -metaData "With XDP Average Latency" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
    }
    catch {
        $currentTestResult.TestSummary += New-ResultSummary -testResult "Error in parsing logs." -metaData "LAGSCOPE" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
    }
    $thresholdLatency = $avgLatency * $thresholdValue
    Write-LogInfo "Average XDP value: $avgLatencyXDP Average w/o XDP value: $avgLatency & threshold: $thresholdLatency"
    if ($avgLatencyXDP -gt $thresholdLatency) {
        Write-LogErr "Average Latency with XDP $avgLatencyXDP is greater than threshold $thresholdLatency"
        return $false
    }
    else {
        return $true
    }
}

function Create_Database_Result {

    $XDPLogDir = $args[0]
    $TestCaseName = $args[1]
    $XDPLogPath = "$LogDir\$XDPLogDir\lagscope-n*-output.txt"
    $LogContents = Get-Content -Path $XDPLogPath
    $TestDate = $(Get-Date -Format yyyy-MM-dd)
    $matchLine = (Select-String -Path $XDPLogPath -Pattern "Average").Line
    $minimumLat = $matchLine.Split(",").Split("=").Trim().Replace("us", "")[1]
    $maximumLat = $matchLine.Split(",").Split("=").Trim().Replace("us", "")[3]
    $averageLat = $matchLine.Split(",").Split("=").Trim().Replace("us", "")[5]
    Write-LogInfo "Generating the performance data for database insertion with $XDPLogDir directory"
    foreach ($line in $LogContents) {
        if ($line -imatch "Interval\(usec\)") {
            $histogramFlag = $true
            continue;
        }
        if ($histogramFlag -eq $false) {
            continue;
        }
        $interval = ($line.Trim() -replace '\s+', ' ').Split(" ")[0]
        $frequency = ($line.Trim() -replace '\s+', ' ').Split(" ")[1]
        if (($interval -match "^\d+$") -and ($frequency -match "^\d+$") -and ($interval -ne "0")) {
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
            $resultMap["ProtocolType"] = "TCP"
            $resultMap["DataPath"] = $XDPLogDir
            $resultMap["MaxLatency_us"] = [Decimal]$maximumLat
            $resultMap["AverageLatency_us"] = [Decimal]$averageLat
            $resultMap["MinLatency_us"] = [Decimal]$minimumLat
            #Percentile Values are not calculated yet. will be added in future
            $resultMap["Latency95Percentile_us"] = 0
            $resultMap["Latency99Percentile_us"] = 0
            $resultMap["Interval_us"] = [int]$interval
            $resultMap["Frequency"] = [int]$frequency
            $currentTestResult.TestResultData += $resultMap
        }
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
        Add-Content -Value "server=$($senderVMData.InternalIP)" -Path $constantsFile
        Add-Content -Value "testServerIP=$($senderVMData.SecondInternalIP)" -Path $constantsFile
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
            -RunInBackground -runAsSudo -ignoreLinuxExitCode
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
        if ($currentState -imatch "TestCompleted") {
            # Start PERF test without XDP
            $ResultDir = "$LogDir\WithoutXDP"
            New-Item -Path $ResultDir -ItemType Directory -Force | Out-Null
            Run_Lagscope_PERF $ResultDir

            # Start XDPDump on client
            # https://lore.kernel.org/lkml/1579558957-62496-3-git-send-email-haiyangz@microsoft.com/t/
            Write-LogDbg "XDP program cannot run with LRO (RSC) enabled, disable LRO before running XDP"
            $xdp_command = "ethtool -K $iFaceName lro off && cd /root/bpf-samples/xdpdump && ./xdpdump -i $iFaceName > ~/xdpdumpoutPERF.txt 2>&1"
            $testJobXDP = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user -password $password -command $xdp_command -RunInBackground -runAsSudo -ignoreLinuxExitCode
            Write-LogInfo "XDP Dump process started with id: $testJobXDP"

            # Start PERF test with XDP
            $ResultDirXDP = "$LogDir\WithXDP"
            New-Item -Path $ResultDirXDP -ItemType Directory -Force | Out-Null
            Run_Lagscope_PERF $ResultDirXDP
            # collect and compare result
            if (Compare_Result $ResultDir $ResultDirXDP) {
                Write-LogInfo "Test Completed"
                $testResult = "PASS"
            }
            else {
                Write-LogErr "Test failed. Lantency result below threshold."
                $testResult = "FAIL"
            }
        }
        elseif ($currentState -imatch "TestAborted") {
            Write-LogErr "Test Aborted. Last known status: $currentStatus."
            $testResult = "ABORTED"
        }
        elseif ($currentState -imatch "TestSkipped") {
            Write-LogErr "Test Skipped. Last known status: $currentStatus"
            $testResult = "SKIPPED"
        }
        elseif ($currentState -imatch "TestFailed") {
            Write-LogErr "Test failed. Last known status: $currentStatus."
            $testResult = "FAIL"
        }
        else {
            Write-LogErr "Test execution is not successful, check test logs in VM."
            $testResult = "ABORTED"
        }
        Copy-RemoteFiles -downloadFrom $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -download `
            -downloadTo $LogDir -files "*.txt, *.log, *.csv" -runAsSudo
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
