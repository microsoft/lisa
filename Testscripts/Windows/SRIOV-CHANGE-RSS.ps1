# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Using iPerf3, get an initial throughput. Change the RSS settings
    and verify if VF is affected. Change RSS settings to the previous
    value and get the throughput again. It should be comparable to the
    initial one.
#>

param ([string] $TestParams, [object] $AllVMData)

function Main {
    param (
        $VMUsername,
        $VMName,
        $HvServer,
        $VMPort,
        $VMPassword,
        $TestParams
    )
    $moduleCheckCMD = "lspci -vvv | grep -c 'mlx[4-5]_core\|mlx4_en\|ixgbevf'"
    $vfCheckCMD = "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci"

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
    Write-LogInfo "The throughput before changing rss profile is $initialThroughput Gbits/sec"


    # Change Rss on test VM
    $rssProfile = Get-NetAdapterRss -Name "*$($TestParams.Switch_Name)*"
    $rssProfile = $rssProfile.Profile
    Write-LogInfo "Changing rss on vSwitch"
    Set-NetAdapterRss -Name "*$($TestParams.Switch_Name))*" -Profile ClosestStatic
    if (-not $?) {
        Write-LogErr "Failed to change rss on vSwitch!"
        Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
        return "FAIL"
    }

    # Check if the SR-IOV module is still loaded
    $moduleCount = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command $moduleCheckCMD -ignoreLinuxExitCode:$true
    if ($moduleCount -lt 1) {
        Write-LogErr "Module is not loaded"
        Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
        return "FAIL"
    }
    # Check if the VF is still present
    $vfCount = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command $vfCheckCMD -ignoreLinuxExitCode:$true
    if ($vfCount -lt 1) {
        Write-LogErr "VF is not present"
        Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
        return "FAIL"
    }

    # Read the throughput again and compare to the previous value
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
    [decimal]$initialThroughput = $initialThroughput * 0.7
    [decimal]$finalThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    Write-LogInfo "The throughput after changing rss profile is $finalThroughput Gbits/sec"
    if ($initialThroughput -gt $finalThroughput) {
        Write-LogErr "After changing rss profile, the throughput decreased"
        Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
        return "FAIL"
    }

    Set-NetAdapterRss -Name "*$($TestParams.Switch_Name)*" -Profile $rssProfile
    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password -VMUsername $user `
    -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
