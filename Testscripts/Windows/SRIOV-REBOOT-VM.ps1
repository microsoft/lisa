# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Reboot the VM and check TX packet count

.Description
    Run iPerf for 30 seconds then reboot. Before rebooting the VM get
    the throughput and TX count. After the reboot, TX cound should be close
    to 0. Start iPerf again and get the throughput. It should be comparable
    to the initial value.
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

    $timeout = 300

    # Get IP
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer
    $vm2ipv4 = Get-IPv4ViaKVP $DependencyVmName $DependencyVmHost

    # Get VF name from vm1
    $vfName = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "ls /sys/class/net | grep -v 'eth0\|eth1\|lo'"

    # Start client on dependency VM
    Run-LinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "iperf3 -s > client.out" -RunInBackGround
    Start-Sleep -Seconds 5
    # Run iPerf on client side for 30 seconds and get the throughput
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$initialThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $initialThroughput){
        Write-LogErr "No result was logged! Check if iPerf was executed!"
        return "FAIL"
    }
    Write-LogInfo "The throughput before restarting VM is $initialThroughput Gbits/sec"
    [int]$txValueBeforeReboot = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "cat /sys/class/net/${vfName}/statistics/tx_packets"
    Write-LogInfo "TX packet count before reboot is $txValueBeforeReboot"

    # Reboot VM1
    Restart-VM -VMName $VMName -ComputerName $HvServer -Force
    $newIpv4 = Get-Ipv4AndWaitForSSHStart $VMName $HvServer $VMPort $VMUsername `
        $VMPassword $timeout
    if (-not $newIpv4) {
        Write-LogErr "Failed to get IP of $VMName on $HvServer"
        return "FAIL"
    }
    # Get the VF name again. In some cases it changes after reboot
    $vfName = Run-LinuxCmd -ip $newIpv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "ls /sys/class/net | grep -v 'eth0\|eth1\|lo'"
    # Get TX packets. The value should be close to 0
    [int]$txValueAfterReboot = Run-LinuxCmd -ip $newIpv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "cat /sys/class/net/${vfName}/statistics/tx_packets"
    if ($txValueAfterReboot -ge $txValueBeforeReboot){
        Write-LogErr "TX packet count didn't decrease after reboot"
        return "FAIL"
    } else {
        Write-LogInfo "TX packet count after reboot is $txValueAfterReboot"
    }

    # Read the throughput again, it should be similar to previous read
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$initialThroughput = $initialThroughput * 0.7
    [decimal]$finalThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    Write-LogInfo "The throughput after restarting the VM is $finalThroughput Gbits/sec"
    if ($initialThroughput -gt $finalThroughput) {
        Write-LogErr "After restarting the VM, the throughput has decreased"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMUsername $user -VMPassword $password
