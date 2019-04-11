# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Disable/Enable SR-IOV on host (using disable/enable-netAdapterSriov) and
    get the throughput using iPerf3

.Description
    Disable SR-IOV from host and get the throughput. Enable SR-IOV and get
    the throughput again. While disabled, the traffic should fallback to the
    synthetic device and throughput should drop. Once SR-IOV is enabled
    again, traffic should handled by the SR-IOV device and throughput increase.
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
    $vm2ipv4 = Get-IPv4ViaKVP $DependencyVmName $DependencyVmHost

    # Start client on dependency VM
    Run-LinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "iperf3 -s > client.out" -RunInBackGround
    Start-Sleep -s 5

    # Run iPerf on client side for 30 seconds with SR-IOV enabled
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"

    [decimal]$vfEnabledThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $vfEnabledThroughput){
        Write-LogErr "No result was logged! Check if iPerf was executed!"
        return "FAIL"
    }
    Write-LogInfo "The throughput before disabling SR-IOV is $vfEnabledThroughput Gbits/sec"

    # Disable SR-IOV on test host and dependency host
    $switchName = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer | `
        Where-Object {$_.SwitchName -like 'SRIOV*'} | Select-Object -ExpandProperty SwitchName
    $hostNICName = Get-VMSwitch -Name $switchName -ComputerName $HvServer | `
        Select-Object -ExpandProperty NetAdapterInterfaceDescription
    $dependencySwitchName = Get-VMNetworkAdapter -VMName $DependencyVmName -ComputerName $DependencyVmHost `
        | Where-Object {$_.SwitchName -like 'SRIOV*'} | Select-Object -ExpandProperty SwitchName
    $dependencyHostNICName = Get-VMSwitch -Name $dependencySwitchName -ComputerName $DependencyVmHost `
        | Select-Object -ExpandProperty NetAdapterInterfaceDescription

    Write-LogInfo "Disabling VF on $hostNICName"
    Disable-NetAdapterSriov -InterfaceDescription $hostNICName -CIMsession $HvServer
    if (-not $?) {
        Write-LogErr "Failed to disable SR-IOV on $hostNICName!"
        Enable-NetAdapterSriov -InterfaceDescription $hostNICName -CIMsession $hvServer
        return "FAIL"
    }
    Disable-NetAdapterSriov -InterfaceDescription $dependencyHostNICName -CIMsession $DependencyVmHost
    if (-not $?) {
        Write-LogErr "Failed to disable SR-IOV on $dependencyHostNICName!"
        Enable-NetAdapterSriov -InterfaceDescription $dependencyHostNICName -CIMsession $DependencyVmHost
        return "FAIL"
    }

    # Wait 1 minute to make sure VF has changed. It is an expected behavior
    Write-LogInfo "Wait 1 minute for VF to be put down"
    Start-Sleep -s 60
    # Get the throughput with SR-IOV disabled; it should be lower
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"

    [decimal]$vfDisabledThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $vfDisabledThroughput){
        Write-LogErr "No result was logged after SR-IOV was disabled!"
        Enable-NetAdapterSriov -InterfaceDescription $hostNICName -CIMsession $hvServer
        return "FAIL"
    }

    Write-LogInfo "The throughput with SR-IOV disabled is $vfDisabledThroughput Gbits/sec"
    if ($vfDisabledThroughput -ge $vfEnabledThroughput) {
        Write-LogErr "The throughput was higher with SR-IOV disabled, it should be lower"
        Enable-NetAdapterSriov -InterfaceDescription $hostNICName -CIMsession $hvServer
        return "FAIL"
    }

    # Enable SR-IOV on test host and dependency host
    Write-LogInfo "Enable VF on on $hostNICName"
    Enable-NetAdapterSriov -InterfaceDescription $hostNICName -CIMsession $hvServer
    if (-not $?) {
        Write-LogErr "Failed to enable SR-IOV on $hostNICName! Please try to manually enable it"
        return "FAIL"
    }
    Enable-NetAdapterSriov -InterfaceDescription $dependencyHostNICName -CIMsession $DependencyVmHost
    if (-not $?) {
        Write-LogErr "Failed to enable SR-IOV on $dependencyHostNICName!"
        return "FAIL"
    }

    # Wait 1 minute to make sure VF has changed. It is an expected behavior
    Write-LogInfo "Wait 1 minute for VF to be put up"
    Start-Sleep -s 60
    # Read the throughput again, it should be higher than before
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$vfDisabledThroughput = $vfDisabledThroughput * 1.5
    [decimal]$vfFinalThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    Write-LogInfo "The throughput after re-enabling SR-IOV is $vfFinalThroughput Gbits/sec"
    if ($vfDisabledThroughput -gt $vfFinalThroughput) {
        Write-LogErr "After re-enabling SR-IOV, the throughput has not increased enough"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMUsername $user -VMPassword $password
