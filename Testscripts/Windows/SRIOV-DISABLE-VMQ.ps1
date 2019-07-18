# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Disable/Enable VMQ on host and get the throughput from iPerf3 each time
    Compare the results and check if throughput is comparable
#>

param ([string] $TestParams, [object] $AllVMData)

function Main {
    param (
        $VmUsername,
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

    [decimal]$initialThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $initialThroughput){
        Write-LogErr "No result was logged! Check if iPerf was executed!"
        return "FAIL"
    }
    Write-LogInfo "The throughput before disabling VMQ is $initialThroughput Gbits/sec"

    # Disable VMQ on test VM
    Write-LogInfo "Disabling VMQ on vm1"
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -VmqWeight 0
    if (-not $?) {
        Write-LogErr "Failed to disable VMQ on $VMName!"
        return "FAIL"
    }

    # Check if the SR-IOV module is still loaded
    $moduleCount = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "lspci -vvv | grep -c 'mlx[4-5]_core\|mlx4_en\|ixgbevf'" `
        -ignoreLinuxExitCode:$true -runAsSudo
    if ($moduleCount -lt 1) {
        Write-LogErr "Module is not loaded"
        return "FAIL"
    }
    # Check if the VF is still present
    $vfCount = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci" `
        -ignoreLinuxExitCode:$true
    if ($vfCount -lt 1) {
        Write-LogErr "VF is not present"
        return "FAIL"
    }

    # Enable VMQ on test VM
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -VmqWeight 0
    if (-not $?) {
        Write-LogErr "Failed to enable VMQ on $VMName!"
        return "FAIL"
    }

    # Read the throughput again, it should be higher than before
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$initialThroughput = $initialThroughput * 0.7
    [decimal]$finalThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    Write-LogInfo "The throughput after re-enabling VMQ is $finalThroughput Gbits/sec"
    if ($initialThroughput -gt $finalThroughput) {
        Write-LogErr "After re-enabling VMQ, the throughput has decreased"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VmUsername $user -VMPassword $password
