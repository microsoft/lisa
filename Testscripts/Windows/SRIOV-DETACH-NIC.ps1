# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Check if VF is unloading/loading when the NIC is detached and attached
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
    $moduleCheckCMD = "lspci -vvv | grep -c 'mlx4_core\|mlx4_en\|ixgbevf'"
    $vfCheckCMD = "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci"

    # Get IP
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer

    # Run Ping with SR-IOV enabled
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; ping -c 600 -I eth1 `$VF_IP2 > PingResults.log" `
        -RunInBackGround

    # Wait 30 seconds and read the RTT
    Start-Sleep -s 30
    [decimal]$initialRTT = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    if (-not $initialRTT){
        LogErr "No result was logged! Check if Ping was executed!"
        return "FAIL"
    }
    LogMsg "The RTT before switching the SR-IOV NIC is $initialRTT ms"

    # Switch SR-IOV NIC to a non-SRIOV NIC
    $nicInfo = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer | Where-Object {$_.SwitchName -like 'SRIOV*'}
    $sriovSwitch = $nicInfo.SwitchName

    # Connect a non-SRIOV vSwitch. We will use the same vSwitch as the management NIC
    [string]$managementSwitch = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer | Select-Object -First 1 | Select-Object -ExpandProperty SwitchName
    Connect-VMNetworkAdapter -VMNetworkAdapter $nicInfo -SwitchName $managementSwitch -Confirm:$False
    if (-not $?) {
        LogErr "Failed to attach another NIC in place of the SR-IOV one"
        return "FAIL"
    }

    # Check if the  SR-IOV module is still loaded
    $moduleCount = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command $moduleCheckCMD -ignoreLinuxExitCode:$true
    if ($moduleCount -gt 0) {
        LogErr "Module is still loaded"
        return "FAIL"
    }

    # Check if the VF is still present
    $vfCount = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command $vfCheckCMD -ignoreLinuxExitCode:$true
    if ($vfCount -gt 0) {
        LogErr "VF is still present"
        return "FAIL"
    }

    # Connect SR-IOV adapter
    Connect-VMNetworkAdapter -VMNetworkAdapter $nicInfo -SwitchName $sriovSwitch -Confirm:$False
    if (-not $?) {
        LogErr "Failed to re-attach the SR-IOV NIC"
        return "FAIL"
    }

    Start-Sleep -s 30
    # Read the RTT again, it should be lower than before
    # We should see values to close to the initial RTT measured
    [decimal]$initialRTT = $initialRTT * 1.7
    [decimal]$vfFinalRTT = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    LogMsg "The RTT after re-attaching the SR-IOV NIC, RTT is $vfFinalRTT ms"
    if ($vfFinalRTT -gt $initialRTT) {
        LogErr "After Re-attaching the SR-IOV NIC, the RTT value has not lowered enough"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password