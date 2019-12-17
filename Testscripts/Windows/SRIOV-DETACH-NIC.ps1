# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Check if VF is unloading/loading when the NIC is detached and attached
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
    $moduleCheckCMD = "lspci -vvv | grep -c 'mlx[4-5]_core\|mlx4_en\|ixgbevf'"
    $vfCheckCMD = "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci"

    # Get IP
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer

    # Run Ping with SR-IOV enabled
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "source sriov_constants.sh ; ping -c 600 -I eth1 `$VF_IP2 > PingResults.log" `
        -RunInBackGround

    # Wait 30 seconds and read the RTT
    Start-Sleep -Seconds 30
    [decimal]$initialRTT = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    if (-not $initialRTT){
        Write-LogErr "No result was logged! Check if Ping was executed!"
        return "FAIL"
    }
    Write-LogInfo "The RTT before switching the SR-IOV NIC is $initialRTT ms"

    # Switch SR-IOV NIC to a non-SRIOV NIC
    $nicInfo = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer | Where-Object {$_.SwitchName -like 'SRIOV*'}
    $sriovSwitch = $nicInfo.SwitchName

    # Connect a non-SRIOV vSwitch. We will use the same vSwitch as the management NIC
    [string]$managementSwitch = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer `
        | Select-Object -First 1 | Select-Object -ExpandProperty SwitchName
    Connect-VMNetworkAdapter -VMNetworkAdapter $nicInfo -SwitchName $managementSwitch -Confirm:$False
    if (-not $?) {
        Write-LogErr "Failed to attach another NIC in place of the SR-IOV one"
        return "FAIL"
    }

    # Check if the  SR-IOV module is still loaded
    $moduleCount = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command $moduleCheckCMD -ignoreLinuxExitCode:$true -runAsSudo
    if ($moduleCount -gt 0) {
        Write-LogErr "Module is still loaded"
        return "FAIL"
    }

    # Check if the VF is still present
    $vfCount = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command $vfCheckCMD -ignoreLinuxExitCode:$true
    if ($vfCount -gt 0) {
        Write-LogErr "VF is still present"
        return "FAIL"
    }

    # Connect SR-IOV adapter
    Connect-VMNetworkAdapter -VMNetworkAdapter $nicInfo -SwitchName $sriovSwitch -Confirm:$False
    if (-not $?) {
        Write-LogErr "Failed to re-attach the SR-IOV NIC"
        return "FAIL"
    }

    Start-Sleep -Seconds 30
    # Read the RTT again, it should be lower than before
    # We should see values to close to the initial RTT measured
    [decimal]$initialRTT = $initialRTT * 1.7
    [decimal]$vfFinalRTT = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
        $VMPassword -command "tail -5 PingResults.log | head -1 | awk '{print `$7}' | sed 's/=/ /' | awk '{print `$2}'" `
        -ignoreLinuxExitCode:$true
    Write-LogInfo "The RTT after re-attaching the SR-IOV NIC, RTT is $vfFinalRTT ms"
    if ($vfFinalRTT -gt $initialRTT) {
        Write-LogErr "After Re-attaching the SR-IOV NIC, the RTT value has not lowered enough"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMUsername $user -VMPassword $password
