# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Check throughput with SR-IOV enabled/disabled from VM Settings

.Description
    Disable SR-IOV from VM Settings (using set-VmNetworkAdapter) and get the
    throughpt. Enable SR-IOV and get the throughput again. While disabled,
    the traffic should fallback to the synthetic device and throughput should
    drop. Once SR-IOV is enabled again, traffic should handled by the SR-IOV
    device and throughput increase.
#>

param ([string] $TestParams)

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
    $vm2ipv4 = Get-IPv4ViaKVP $DependencyVmName $DependencyVmHost

    # Start client on dependency VM
    RunLinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "iperf3 -s > client.out" -RunInBackGround
    Start-Sleep -s 5

    # Run iPerf on client side for 30 seconds with SR-IOV enabled
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"

    [decimal]$vfEnabledThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $vfEnabledThroughput){
        LogErr "No result was logged! Check if iPerf was executed!"
        return "FAIL"
    }
    LogMsg "The throughput before disabling SR-IOV is $vfEnabledThroughput Gbits/sec"

    # Disable SR-IOV on test VM
    LogMsg "Disabling VF on vm1"
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IovWeight 0
    if (-not $?) {
        LogErr "Failed to disable SR-IOV on $VMName!"
        return "FAIL"
    }

    # Get the throughput with SR-IOV disabled; it should be lower
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"

    [decimal]$vfDisabledThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $vfDisabledThroughput){
        LogErr "No result was logged after SR-IOV was disabled!"
        return "FAIL"
    }

    LogMsg "The throughput with SR-IOV disabled is $vfDisabledThroughput Gbits/sec"
    if ($vfDisabledThroughput -ge $vfEnabledThroughput) {
        LogErr "The throughput was higher with SR-IOV disabled, it should be lower"
        return "FAIL"
    }

    # Enable SR-IOV on test VM
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IovWeight 1
    if (-not $?) {
        LogErr "Failed to enable SR-IOV on $VMName!"
        return "FAIL"
    }

    # Read the throughput again, it should be higher than before
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$vfEnabledThroughput  = $vfEnabledThroughput * 0.7
    [decimal]$vfFinalThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    LogMsg "The throughput after re-enabling SR-IOV is $vfFinalThroughput Gbits/sec"
    if ($vfEnabledThroughput -gt $vfFinalThroughput) {
        LogErr "After re-enabling SR-IOV, the throughput has not increased enough"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password
