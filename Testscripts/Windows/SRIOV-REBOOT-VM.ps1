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

param ([string] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMPassword
    )
    $VMRootUser = "root"
    $timeout = 300

    # Get IP
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer
    $vm2ipv4 = Get-IPv4ViaKVP $DependencyVmName $DependencyVmHost

    # Get VF name from vm1
    $vfName = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "ls /sys/class/net | grep -v 'eth0\|eth1\|lo'"

    # Start client on dependency VM
    RunLinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "iperf3 -s > client.out" -RunInBackGround
    Start-Sleep -s 5
    # Run iPerf on client side for 30 seconds and get the throughput
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$initialThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $initialThroughput){
        LogErr "No result was logged! Check if iPerf was executed!"
        return "FAIL"
    }
    LogMsg "The throughput before restarting VM is $initialThroughput Gbits/sec"
    [int]$txValueBeforeReboot = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "cat /sys/class/net/${vfName}/statistics/tx_packets"
    LogMsg "TX packet count before reboot is $txValueBeforeReboot"

    # Reboot VM1
    Restart-VM -VMName $VMName -ComputerName $HvServer -Force
    $newIpv4 = Get-Ipv4AndWaitForSSHStart $VMName $HvServer $VMPort $VMRootUser `
        $VMPassword $timeout
    if ($null -eq $newIpv4) {
        LogErr "Failed to get IP of $VMName on $HvServer"
        return "FAIL"
    }
    # Get the VF name again. In some cases it changes after reboot
    $vfName = RunLinuxCmd -ip $newIpv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "ls /sys/class/net | grep -v 'eth0\|eth1\|lo'"
    # Get TX packets. The value should be close to 0
    [int]$txValueAfterReboot = RunLinuxCmd -ip $newIpv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "cat /sys/class/net/${vfName}/statistics/tx_packets"
    if ($txValueAfterReboot -ge $txValueBeforeReboot){
        LogErr "TX packet count didn't decrease after reboot"
        return "FAIL"
    } else {
        LogMsg "TX packet count after reboot is $txValueAfterReboot"
    }

    # Read the throughput again, it should be similar to previous read
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$initialThroughput = $initialThroughput * 0.7
    [decimal]$finalThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    LogMsg "The throughput after restarting the VM is $finalThroughput Gbits/sec"
    if ($initialThroughput -gt $finalThroughput) {
        LogErr "After restarting the VM, the throughput has decreased"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password