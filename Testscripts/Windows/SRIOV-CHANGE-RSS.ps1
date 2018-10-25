# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Using iPerf3, get an initial throughput. Change the RSS settings
    and verify if VF is affected. Change RSS settings to the previous
    value and get the throughput again. It should be comparable to the
    initial one.
#>

param ([string] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMPassword,
        $TestParams
    )
    $VMRootUser = "root"
    $moduleCheckCMD = "lspci -vvv | grep -c 'mlx4_core\|mlx4_en\|ixgbevf'"
    $vfCheckCMD = "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci"

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
    LogMsg "The throughput before changing rss profile is $initialThroughput Gbits/sec"


    # Change Rss on test VM
    $rssProfile = Get-NetAdapterRss -Name "*$($TestParams.Switch_Name)*"
    $rssProfile = $rssProfile.Profile
    LogMsg "Changing rss on vSwitch"
    Set-NetAdapterRss -Name "*$($TestParams.Switch_Name))*" -Profile ClosestStatic
    if (-not $?) {
        LogErr "Failed to change rss on vSwitch!"
        Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
        return "FAIL"
    }

    # Check if the SR-IOV module is still loaded
    $moduleCount = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command $moduleCheckCMD -ignoreLinuxExitCode:$true
    if ($moduleCount -lt 1) {
        LogErr "Module is not loaded"
        Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
        return "FAIL"
    }
    # Check if the VF is still present
    $vfCount = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command $vfCheckCMD -ignoreLinuxExitCode:$true
    if ($vfCount -lt 1) {
        LogErr "VF is not present"
        Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
        return "FAIL"
    }

    # Read the throughput again and compare to the previous value
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$initialThroughput = $initialThroughput * 0.7
    [decimal]$finalThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    LogMsg "The throughput after changing rss profile is $finalThroughput Gbits/sec"
    if ($initialThroughput -gt $finalThroughput) {
        LogErr "After changing rss profile, the throughput decreased"
        Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
        return "FAIL"
    }

    Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password `
    -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) 