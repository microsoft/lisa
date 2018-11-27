# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    Configure a VM with the parameters defined in the XML global section, for example vmCpuNumber, vmMemory, etc.
#>

param([String] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )

    # Define used variables
    $vmCpuNumber = 0
    $vmMemory = 0GB

    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "vmCpuNumber" {$vmCpuNumber = $fields[1].Trim()}
            "vmMemory" {$vmMemory = $fields[1].Trim()}
            default {}
        }
    }

    if ($vmCpuNumber -ne 0) {
        Write-LogInfo "CPU: $vmCpuNumber"
        Set-VM -ComputerName $HvServer -VMName $VMName -ProcessorCount $vmCpuNumber
        Set-VMProcessor -ComputerName $HvServer -VMName $VMName -Reserve 100
    }

    if ($vmMemory -ne 0GB) {
        $regex = "(\d+)([G|g|M|m])([B|b])"
        if ($vmMemory -match $regex) {
            $num=$Matches[1].Trim()
            $mg=$Matches[2].Trim()
            $b=$Matches[3].Trim()

            [int64]$memorySize = 1024 * 1024
            if ($mg.Contains('G')) {
                $memorySize = $memorySize * 1024 * $num
            } else {
                $memorySize = $memorySize * $num
            }

            Write-LogInfo "Memory: $memorySize Bytes ($($num+$mg+$b))"
            if ($memorySize -gt 32 * 1024 * 1024) {
                Set-VM -ComputerName $HvServer -VMName $VMName -MemoryStartupBytes $memorySize
            } else {
                Write-LogInfo"Memory size is provided but it is too small (should greater than 32MB): $vmMemory"
                return $false
            }
        } else {
            Write-LogInfo "Memory size is provided but it is not recognized: $vmMemory. Example: 2GB or 200MB"
            return $false
        }
    }

    return $true
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -testParams $TestParams
