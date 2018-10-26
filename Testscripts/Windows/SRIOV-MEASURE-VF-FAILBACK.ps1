# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Disable SR-IOV while transferring data of the device, then enable SR-IOV.
    For both operations, measure time between the switch.
    If the time is bigger than 30 seconds, fail the test
#>

param ([string] $TestParams)

function Measure-TimeToSwitch {
    param (
        $ExpectedVfNumber,
        $VMuser,
        $VMIp,
        $VMPass,
        $VMPort
    )

    $timeToRun = 0
    $hasSwitched = $false
    while ($hasSwitched -eq $false) {
        # Check if the VF is still present
        $vfCount = RunLinuxCmd -ip $VMIp -port $VMPort -username $VMuser -password `
            $VMPass -command "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci" `
            -ignoreLinuxExitCode:$true
        if ($vfCount -eq $ExpectedVfNumber) {
            $hasSwitched = $true
        }

        $timeToRun++
        if ($timeToRun -ge 30) {
            LogErr "The switch beteen VF and netvsc was not made"
            return $false
        }

        if ($hasSwitched -eq $false){
            Start-Sleep -s 1
        }
    }
    LogMsg "Failback was made in $timeToRun second(s)"
    return $true
}

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMPassword
    )
    $VMRootUser = "root"

    # Get IP
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer

    # Run Ping with SR-IOV enabled
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; ping -c 600 -I eth1 `$VF_IP2 > PingResults.log" `
        -RunInBackGround

    # Wait 30 seconds and read the RTT
    Start-Sleep -s 30
    [decimal]$vfEnabledRTT = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    if (-not $vfEnabledRTT){
        LogErr "No result was logged! Check if Ping was executed!"
        return "FAIL"
    }
    LogMsg "The RTT before disabling SR-IOV is $vfEnabledRTT ms"

    # Disable SR-IOV on test VM
    Start-Sleep -s 5
    LogMsg "Disabling VF on vm1"
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IovWeight 0
    if (-not $?) {
        LogErr "Failed to disable SR-IOV on $VMName!"
        return "FAIL"
    }
    # Measure the failback time
    Measure-TimeToSwitch "0" $VMRootUser $ipv4 $VMPassword $VMPort
    if (-not $?) {
        LogErr "Failback time is too high"
        return "FAIL"
    }

    # Enable SR-IOV on test VM
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IovWeight 1
    if (-not $?) {
        LogErr "Failed to enable SR-IOV on $VMName!"
        return "FAIL"
    }
    # Measure the failback time
    Measure-TimeToSwitch "1" $VMRootUser $ipv4 $VMPassword $VMPort
    if (-not $?) {
        LogErr "Failback time is too high"
        return "FAIL"
    }

    # Read the RTT again, it should be lower than before
    # We should see values to close to the initial RTT measured
    Start-Sleep 10
    [decimal]$vfEnabledRTT = $vfEnabledRTT * 1.3
    [decimal]$vfFinalRTT = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    LogMsg "The RTT after re-enabling SR-IOV is $vfFinalRTT ms"
    if ($vfFinalRTT -gt $vfEnabledRTT) {
        LogErr "After re-enabling SR-IOV, the RTT value has not lowered enough"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password