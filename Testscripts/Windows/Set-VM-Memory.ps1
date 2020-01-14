# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This is a Powershell script that sets the RAM memory of a VM
#>

param (
    [string] $vmName,
    [string] $hvServer,
    [string] $testParams,
    [object] $AllVMData
)

function Main {
    param (
        [string] $vmName,
        [string] $hvServer
    )

    $VMMemory = $null
    $startupMemory = $null

    if (-not $vmName -or $vmName.Length -eq 0) {
        Write-LogErr "vmName is null"
        return $False
    }

    if (-not $hvServer -or $hvServer.Length -eq 0) {
        Write-LogErr "hvServer is null"
        return $False
    }

    if (-not $testParams) {
        Write-LogErr "testParams is null"
        return $False
    }

    $params = $testParams.TrimEnd(";").Split(";")
    foreach ($param in $params) {
        $fields = $param.Split("=")
        switch ($fields[0].Trim()) {
            "VMMemory" {$VMMemory = $fields[1].Trim()}
            "memWeight" {$memWeight = $fields[1].Trim()}
            "staticMem" {$staticMem = $fields[1].Trim()}
            default {}
        }
    }

    $startupMemory = Convert-StringToDecimal $VMMemory
    $availableMemory = [string](Get-Counter -Counter "\Memory\Available MBytes" -ComputerName $hvServer).CounterSamples[0].CookedValue + "MB"
    $availableMemory = Convert-StringToDecimal $availableMemory

    if ($startupMemory -gt $availableMemory) {
        Write-LogErr "Not enough available memory on the system. startupMemory: $startupMemory, free space: $availableMemory"
        return $False
    }

    if ($staticMem -eq "true") {
        Set-VMMemory -VMName $vmName -ComputerName $hvServer -StartupBytes $startupMemory -Priority $memWeight
    } else {
        $vm = Get-VM -VMName $vmName -ComputerName $hvServer
        if ($vm.DynamicMemoryEnabled) {
            Set-VMMemory -VMName $vmName -ComputerName $hvServer -StartupBytes $startupMemory -MaximumBytes $startupMemory -MinimumBytes $startupMemory -Confirm:$False -Priority $memWeight
        }
    }

    if (-not $?) {
        Write-LogErr "Unable to set ${VMMemory} of RAM for ${vmName}"
        return $False
    }

    Write-LogInfo "Success: Setting $VMMemory of RAM for $vmName updated successful"
    return $True
}

if ($vmName) {
    $vm = $vmName
} else {
    $vm = $AllVMData.RoleName
}

if ($hvServer) {
   $server = $hvServer
} else {
    $server = $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName
}

Main -vmName $vm -hvServer $server
