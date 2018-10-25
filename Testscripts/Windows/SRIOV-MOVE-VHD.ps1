# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Create a new Linux VM from an existing VHDX file that has SR-IOV
    configured. SR-IOV should be configured correctly and should work
    when the new VM is booted.
#>

param ([string] $TestParams)

function Remove-Data {
    param (
        $ChildVMName,
        $HvServer,
        $ChildVHD
    )
    # Clean up
    Stop-VM -Name $ChildVMName -ComputerName $HvServer -TurnOff -EA SilentlyContinue

    # Delete New VM created
    Remove-VM -Name $ChildVMName -ComputerName $HvServer -Confirm:$false -Force -EA SilentlyContinue

    # Delete vhd
    Remove-Item $ChildVHD -Force -EA SilentlyContinue
}

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMPassword
    )
    $VMRootUser = "root"
    $childVMName = "SRIOV_Child"
    $sriovNIC = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer | Where-Object {$_.SwitchName -like 'SRIOV*'}
    $managementNIC = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer | Select-Object -First 1 | Select-Object -ExpandProperty SwitchName
    $defaultVhdPath = (Get-VMHost -ComputerName $HvServer).VirtualHardDiskPath
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }
    $childVhdPath ="${defaultVhdPath}SRIOV_ChildRemote"

    # Get IP
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer
    # Run Ping with SR-IOV enabled
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; ping -c 20 -I eth1 `$VF_IP2 > PingResults.log"

    [decimal]$initialRTT = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -1 PingResults.log | sed 's/\// /g' | awk '{print `$8}'" `
        -ignoreLinuxExitCode:$true
    if (-not $initialRTT){
        LogErr "No result was logged! Check if Ping was executed!"
        return "FAIL"
    }
    LogMsg "The RTT on the parent VM is $initialRTT ms"

    # Stop VM and get the vhd
    Stop-VM $VMName -ComputerName $HvServer -Force
    $vhdLocation = (Get-VM $VMName -ComputerName $HvServer).HardDrives[0].Path
    $extension = (Get-Item $vhdLocation | Select-Object Extension).Extension
    $childVhdPath = $vhdLocation + $extension
    xcopy $vhdLocation $childVhdPath* /Y
    if (-not $?) {
        LogErr "Failed to make a copy of the parent vhd"
        return "FAIL"
    }

    # Get the parent VM info and create a new VM
    $vmGen = Get-VMGeneration $VMName $HvServer
    New-VM -Name $childVMName -ComputerName $HvServer -VHDPath $childVhdPath `
        -MemoryStartupBytes 4096MB -SwitchName $managementNIC -Generation $vmGen
    if (-not $?) {
        LogErr "Failed to create a SRIOV Child VM on $HvServer"
        return "FAIL"
    }
    # Disable secure boot if Gen2
    if ($vmGen -eq 2) {
        Set-VMFirmware -VMName $childVMName -ComputerName $hvServer -EnableSecureBoot Off
        if (-not $?) {
            LogErr "Unable to disable secure boot"
            Remove-Data $childVMName $HvServer $childVhdPath
            return "FAIL"
        }
    }
    Add-VMNetworkAdapter -VMName $childVMName  -SwitchName $sriovNIC.SwitchName -IsLegacy:$false -ComputerName $HvServer
    if (-not $?) {
        LogErr "Failed to attach SRIOV NIC"
        Remove-Data $childVMName $HvServer $childVhdPath
        return "FAIL"
    }
    Set-VMNetworkAdapter -VMName $childVMName -ComputerName $HvServer -IovWeight 1
    if ($? -ne "True") {
        LogErr "Failed to enable SR-IOV on $VMName!"
        Remove-Data $childVMName $HvServer $childVhdPath
        return "FAIL"
    }

    $initialRTT = $initialRTT * 1.4
    $newIpv4 = Start-VMandGetIP $childVMName $HvServer $VMPort $VMRootUser $VMPassword
    RunLinuxCmd -ip $newIpv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; ping -c 20 -I eth1 `$VF_IP2 > PingResults.log"

    [decimal]$finalRTT = RunLinuxCmd -ip  $newIpv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -1 PingResults.log | sed 's/\// /g' | awk '{print `$8}'" `
        -ignoreLinuxExitCode:$true
    if (-not $finalRTT){
        LogErr "No result was logged! Check if Ping was executed!"
        Remove-Data $childVMName $HvServer $childVhdPath
        return "FAIL"
    }
    LogMsg "The RTT on the child VM is $finalRTT ms"
    if ($finalRTT -gt $initialRTT) {
        LogErr "After re-enabling SR-IOV, the RTT value has not lowered enough"
        Remove-Data $childVMName $HvServer $childVhdPath
        return "FAIL"
    }

    Remove-Data $childVMName $HvServer $childVhdPath
    Start-VMandGetIP $VMName $HvServer $VMPort $VMRootUser $VMPassword
    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password