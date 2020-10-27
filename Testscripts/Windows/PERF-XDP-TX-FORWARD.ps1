# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This script deploys the VM and Verifies there are no regression in Network Latency caused
    by XDP. We achieve this by comparing lagscope results.
#>

param([object] $AllVmData,
    [object] $CurrentTestData)

function Main {
    try {
        # PROVISION VMS FOR LISA WILL ENABLE ROOT USER AND WILL MAKE ENABLE PASSWORDLESS AUTHENTICATION ACROSS ALL VMS.
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

        Write-LogInfo "Generating constants.sh ..."
        $constantsFile = "$LogDir\constants.sh"

        foreach ($vmData in $allVMData) {
            if ($vmData.RoleName -eq "sender") {
                $masterVM = $vmData
            }

            Write-LogInfo "VM $($vmData.RoleName) details :"
            Write-LogInfo "  Public IP : $($vmData.PublicIP)"
            Write-LogInfo "  SSH Port : $($vmData.SSHPort)"
            Write-LogInfo "  Internal IP : $($vmData.InternalIP)"
            Write-LogInfo ""

            Add-Content -Value "$($vmData.RoleName)=$($vmData.InternalIP)" -Path $constantsFile
            Add-Content -Value "$($vmData.RoleName)SecondIP=$($vmData.SecondInternalIP)" -Path $constantsFile
        }

        if ($null -eq $masterVM) {
            Throw "PERF-XDP-TX-FORWARD requires at least one VM with RoleName of sender"
        }

        foreach ($param in $currentTestData.TestParameters.param) {
            Add-Content -Value "$param" -Path $constantsFile
        }
        # Add modes according to testcase
        if ( $CurrentTestData.testName -match "TX" ){
            Add-Content -Value "modes=(xdp)" -Path $constantsFile
            $testDuration=15
        }
        else {
            Add-Content -Value "modes=(xdp iptables)" -Path $constantsFile
            $testDuration=50
        }
        Write-LogInfo "constants.sh created successfully..."
        Write-LogInfo (Get-Content -Path $constantsFile)

        # Start XDP Installation
        $installXDPCommand = @"
bash ./XDPForwardingTest.sh ${testDuration} 2>&1 > ~/xdpConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
        Set-Content "$LogDir\StartXDPSetup.sh" $installXDPCommand
        Copy-RemoteFiles -uploadTo $masterVM.PublicIP -port $masterVM.SSHPort `
            -files "$constantsFile,$LogDir\StartXDPSetup.sh" `
            -username $user -password $password -upload -runAsSudo
        # IF Single core then enable single core only
        $testJob = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort `
            -username $user -password $password -command "bash ./StartXDPSetup.sh" `
            -RunInBackground -runAsSudo
        # Terminate process if ran more than 5 mins
        # TODO: Check max installation time for other distros when added
        $timer = 0
        while ($testJob -and ((Get-Job -Id $testJob).State -eq "Running")) {
            $currentStatus = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort `
                -username $user -password $password -command "tail -2 ~/xdpConsoleLogs.txt | head -1" -runAsSudo
            Write-LogInfo "Current Test Status: $currentStatus"
            Wait-Time -seconds 20
            $timer += 1
            if ($timer -gt 30) {
                Throw "XDPFowardingTest did not stop after 10 mins. Please check xdpConsoleLogs."
            }
        }

        $currentState = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort `
            -username $user -password $password -command "cat state.txt" -runAsSudo

        if ($currentState -imatch "TestCompleted") {
            Write-LogInfo "Test Completed"
            $testResult = "PASS"
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
        Copy-RemoteFiles -downloadFrom $masterVM.PublicIP -port $masterVM.SSHPort `
            -username $user -password $password -download `
            -downloadTo $LogDir -files "*.txt, *.log,*.csv" -runAsSudo
        if ( $testResult -eq "PASS" ) {
            $TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
            if (!$TestCaseName) {
                $TestCaseName = $CurrentTestData.testName
            }
            $reportCsv = Import-Csv -Path "$LogDir\report.csv"
            $TestDate = $(Get-Date -Format yyyy-MM-dd)
            $testType = "TX"
            Write-LogInfo "Generating the performance data for database insertion."
            foreach ($mode in $reportCsv) {
                $resultMap = @{}
                $resultMap["TestCaseName"] = $TestCaseName
                $resultMap["TestDate"] = $TestDate
                $resultMap["HostType"] = $TestPlatform
                $resultMap["HostBy"] = $CurrentTestData.SetupConfig.TestLocation
                $resultMap["HostOS"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version" | ForEach-Object { $_ -replace ",Host Version,", "" })
                $resultMap["GuestOSType"] = "Linux"
                $resultMap["GuestDistro"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type" | ForEach-Object { $_ -replace ",OS type,", "" })
                $resultMap["GuestSize"] = $masterVM.InstanceSize
                $resultMap["KernelVersion"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version" | ForEach-Object { $_ -replace ",Kernel version,", "" })
                $resultMap["IPVersion"] = "IPv4"
                $resultMap["XDPAction"] = $testType
                $resultMap["DataPath"] = $mode.data_path
                $resultMap["TestType"] = $mode.test_type
                $resultMap["SenderPPS"] = $mode.sender_pps
                $resultMap["NumberOfPacketsSent"] = $mode.packets_sent
                $resultMap["NumberOfPacketsForwarded"] = $mode.packets_forwarded
                $resultMap["NumberOfPacketsReceived"] = $mode.packets_received
                $currentTestResult.TestResultData += $resultMap
            }
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
