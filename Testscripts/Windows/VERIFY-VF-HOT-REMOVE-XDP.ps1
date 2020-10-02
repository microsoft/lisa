# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This script deploys the VM, build and Install xdpdump application
    Verify VF Hot removal and add works as expected
#>

param([object] $AllVmData,
    [object] $CurrentTestData)

# This function will add or remove VF from VM
function Set_VF {
    $vmData = $args[0]
    $accNetFlag = $args[1]
    # Additional NIC on the VMs are named with a keyword "Extra"
    $extraNIC = Get-AzNetworkInterface -ResourceGroupName $vmData.ResourceGroupName | Where-Object { $_.Name -match "$($vmData.RoleName)-Extra" }
    if ($null -eq $extraNIC) {
        Throw "Cannot access Extra NIC on $($vmData.RoleName) VM"
    }
    $extraNIC.EnableAcceleratedNetworking = $accNetFlag
    $out = $extraNIC | Set-AzNetworkInterface
    if ($out.EnableAcceleratedNetworking -eq $accNetFlag) {
        Write-LogInfo "Accelerated Networking on $($extraNIC.name) set to $accNetFlag"
    }
    else {
        Throw "Error while setting Accelerated Networing to $accNetFlag"
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
            Throw "No receiver VM defined. Aborting Test."
        }
        if ($noSender) {
            Throw "No sender VM defined. Aborting Test."
        }

        #CONFIGURE VM Details
        Write-LogInfo "Receiver VM details :"
        Write-LogInfo "  RoleName : $($receiverVMData.RoleName)"
        Write-LogInfo "  Public IP : $($receiverVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($receiverVMData.SSHPort)"
        Write-LogInfo "  Internal IP : $($receiverVMData.InternalIP)"
        Write-LogInfo "Sender VM details :"
        Write-LogInfo "  RoleName : $($senderVMData.RoleName)"
        Write-LogInfo "  Public IP : $($senderVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($senderVMData.SSHPort)"
        Write-LogInfo "  Internal IP : $($senderVMData.InternalIP)"

        # PROVISION VMS FOR LISA WILL ENABLE ROOT USER AND WILL MAKE ENABLE PASSWORDLESS AUTHENTICATION ACROSS ALL VMS.
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

        $iFaceName = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -command ". utils.sh && get_extra_synth_nic"
        if ($null -eq $iFaceName) {
            Throw "Extra Synthetic interface name in VM not found"
        }
        $installXDPCommand = @"
./XDPDumpSetup.sh $($receiverVMData.InternalIP) $iFaceName 2>&1 > ~/xdpConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
        Set-Content "$LogDir\StartXDPSetup.sh" $installXDPCommand
        Copy-RemoteFiles -uploadTo $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -files "$LogDir\StartXDPSetup.sh" `
            -username $user -password $password -upload -runAsSudo

        Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -command "chmod +x *.sh" -runAsSudo | Out-Null
        $testJob = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -command "./StartXDPSetup.sh" `
            -RunInBackground -runAsSudo -ignoreLinuxExitCode
        $timer = 0
        while ($testJob -and ((Get-Job -Id $testJob).State -eq "Running")) {
            $currentStatus = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
                -username $user -password $password -command "tail -2 ~/xdpConsoleLogs.txt | head -1" -runAsSudo
            Write-LogInfo "Current Test Status: $currentStatus"
            Wait-Time -seconds 20
            $timer += 1
            if ($timer -gt 15) {
                Throw "XDPSetup did not stop after 5 mins. Please check logs."
            }
        }

        $currentState = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -command "cat state.txt" -runAsSudo
        if ($currentState -imatch "TestCompleted") {
            Write-LogInfo "XDPSetup successfully ran on $($receiverVMDAta.RoleName)"
            # Start ping and xdpdump
            $ping_command = "ping -I $iFaceName -c 300 $($senderVMData.SecondInternalIP) > ~/pingOut$LogSuffix.txt"
            Write-LogInfo "Starting command: $ping_command on $($receiverVMData.RoleName)"
            Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user -password $password `
                -command $ping_command -RunInBackground -runAsSudo
            Write-LogDbg "XDP program cannot run with LRO (RSC) enabled, disable LRO before running XDP"
            $xdp_command = "ethtool -K $iFaceName lro off && cd ~/bpf-samples/xdpdump && ./xdpdump -i $iFaceName > ~/xdpdumpout_VFTest.txt 2>&1"
            $testJob = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user -password $password `
                -command $xdp_command -RunInBackground -runAsSudo -ignoreLinuxExitCode

            Wait-Time -seconds 10
            Set_VF $receiverVMData $false
            Wait-Time -seconds 20
            Set_VF $receiverVMData $true
            Wait-Time -seconds 10
            # Kill and verify XDP unloaded successfully
            if ((Get-Job -Id $testJob).State -eq "Running") {
                Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user -password $password `
                    -command "pkill -f xdpdump" -runAsSudo
                $currentStatus = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user -password $password `
                    -command "tail -1 ~/xdpdumpout_VFTest.txt" -runAsSudo
                if ($currentStatus -inotmatch "unloading xdp") {
                    Throw "XDP Dump program did not exit as expected on ip:$($receiverVMData.PublicIP) device:$IFaceName"
                }
            }
            else {
                Throw "XDP Dump stopped unexpectedly."
            }
            Write-LogInfo "VF Hot Remove with XDP verified successfully"
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

        Copy-RemoteFiles -downloadFrom $receiverVMData.PublicIP -port $receiverVMData.SSHPort `
            -username $user -password $password -download `
            -downloadTo $LogDir -files "*.txt, *.log, *.csv"
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
        $testResult = "ABORTED"
    }
    finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    Write-LogInfo "Test result: $testResult"
    return $testResult
}

Main