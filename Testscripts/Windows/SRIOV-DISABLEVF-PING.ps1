# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Check RTT with SR-IOV enabled/disabled from VM Settings

.Description
    Continuously ping a server, from a Linux client, over a SR-IOV connection.
    Disable SR-IOV on the Linux client and observe RTT increase.
    Re-enable SR-IOV and observe that RTT lowers.
#>

param ([string] $TestParams, [object] $AllVMData)

function Main {
    param (
        $VMUsername,
        $VMName,
        $HvServer,
        $VMPort,
        $VMPassword
    )

    # Get IP
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer

    # Run Ping with SR-IOV enabled
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; ping -c 600 -I eth1 `$VF_IP2 > PingResults.log" `
        -RunInBackGround

    # Wait 30 seconds and read the RTT
    Start-Sleep -s 30
    [decimal]$vfEnabledRTT = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    if (-not $vfEnabledRTT){
        Write-LogErr "No result was logged! Check if Ping was executed!"
        return "FAIL"
    }
    Write-LogInfo "The RTT before disabling SR-IOV is $vfEnabledRTT ms"

    # Disable SR-IOV on test VM and dependency VM
    Start-Sleep -s 5
    Write-LogInfo "Disabling VF on vm1"
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IovWeight 0
    if (-not $?) {
        Write-LogErr "Failed to disable SR-IOV on $VMName!"
        return "FAIL"
    }
    Set-VMNetworkAdapter -VMName $DependencyVmName -ComputerName $DependencyVmHost -IovWeight 0
    if (-not $?) {
        Write-LogErr "Failed to disable SR-IOV on $DependencyVmName!"
        return "FAIL"
    }

    # Read the RTT with SR-IOV disabled; it should be higher
    Start-Sleep -s 30
    [decimal]$vfDisabledRTT = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    if (-not $vfDisabledRTT){
        Write-LogErr "No result was logged after SR-IOV was disabled!"
        return "FAIL"
    }

    Write-LogInfo "The RTT with SR-IOV disabled is $vfDisabledRTT ms"
    if ($vfDisabledRTT -le $vfEnabledRTT) {
        Write-LogErr "The RTT was lower with SR-IOV disabled, it should be higher"
        return "FAIL"
    }

    # Enable SR-IOV on test VM and dependency VM
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IovWeight 1
    if (-not $?) {
        Write-LogErr "Failed to enable SR-IOV on $VMName!"
        return "FAIL"
    }
    Set-VMNetworkAdapter -VMName $DependencyVmName -ComputerName $DependencyVmHost -IovWeight 1
    if (-not $?) {
        Write-LogErr "Failed to enable SR-IOV on $DependencyVmName!"
        return "FAIL"
    }

    Start-Sleep -s 30
    # Read the RTT again, it should be lower than before
    # We should see values to close to the initial RTT measured
    [decimal]$vfEnabledRTT = $vfEnabledRTT * 1.3
    [decimal]$vfFinalRTT = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    Write-LogInfo "The RTT after re-enabling SR-IOV is $vfFinalRTT ms"
    if ($vfFinalRTT -gt $vfEnabledRTT) {
        Write-LogErr "After re-enabling SR-IOV, the RTT value has not lowered enough"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMUsername $user -VMPassword $password
