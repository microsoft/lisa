#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([string] $TestParams, [object] $AllVMData)

function Main {
    param (
        $HvServer,
        $VMName,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )

    $rootUser = "root"

    $params = $testParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        if ($fields[0].Trim() -eq "VMMemory") {
            $startupMem = $fields[1].Trim()
        }
    }

    #Define peak available memory in case of a problem. This value is the maximum value that a VM is able to
    #access in case of MTRR problem. If the guest cannot access more memory than this value the MTRR problem occurs.
    $peakFaultMem = [int]67700

    #Get VM available memory
    $guestReadableMem = Run-LinuxCmd -username $rootUser -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "free -m | grep Mem | xargs | cut -d ' ' -f 2"
    if ($? -ne "True") {
        Write-LogErr "Unable to send command to VM."
        return "FAIL"
    }

    $memInfo = Run-LinuxCmd -username $rootUser -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "cat /proc/meminfo | grep MemTotal | xargs | cut -d ' ' -f 2"
    if ($? -ne "True") {
        Write-LogErr "Unable to send command to VM."
        return "FAIL"
    }
    $memInfo = [math]::floor($memInfo/1024)

    #Check if free binary and /proc/meminfo return the same value
    if ($guestReadableMem -ne $memInfo) {
        Write-LogWarn "Free and proc/meminfo return different values"
    }

    if ($guestReadableMem -gt $peakFaultMem) {
        Write-LogInfo "VM is able to use all the assigned memory"
        return "PASS"
    } else {
        Write-LogErr "VM cannot access all assigned memory."
        Write-LogErr "Assigned: $startupMem MB| VM addressable: $guestReadableMem MB"
        return "FAIL"
    }
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
