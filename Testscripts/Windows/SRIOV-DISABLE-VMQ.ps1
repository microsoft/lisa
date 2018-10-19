# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Disable/Enable VMQ on host and get the throughput from iPerf3 each time
    Compare the results and check if throughput is comparable
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

    [decimal]$initialThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $initialThroughput){
        LogErr "No result was logged! Check if iPerf was executed!"
        return "FAIL"
    }
    LogMsg "The throughput before disabling VMQ is $initialThroughput Gbits/sec"

    # Disable VMQ on test VM
    LogMsg "Disabling VMQ on vm1"
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -VmqWeight 0
    if (-not $?) {
        LogErr "Failed to disable VMQ on $VMName!"
        return "FAIL"
    }

    # Check if the SR-IOV module is still loaded
    $moduleCount = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "lspci -vvv | grep -c 'mlx4_core\|mlx4_en\|ixgbevf'" `
        -ignoreLinuxExitCode:$true
    if ($moduleCount -lt 1) {
        LogErr "Module is not loaded"
        return "FAIL"
    }
    # Check if the VF is still present
    $vfCount = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci" `
        -ignoreLinuxExitCode:$true
    if ($vfCount -lt 1) {
        LogErr "VF is not present"
        return "FAIL"
    }

    # Enable VMQ on test VM
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -VmqWeight 0
    if (-not $?) {
        LogErr "Failed to enable VMQ on $VMName!"
        return "FAIL"
    }

    # Read the throughput again, it should be higher than before
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$initialThroughput = $initialThroughput * 0.7
    [decimal]$finalThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    LogMsg "The throughput after re-enabling VMQ is $finalThroughput Gbits/sec"
    if ($initialThroughput -gt $finalThroughput) {
        LogErr "After re-enabling VMQ, the throughput has decreased"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password