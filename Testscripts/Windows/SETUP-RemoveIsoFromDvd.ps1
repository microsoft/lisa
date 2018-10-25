# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Remove all DVD drives from VM.

.Description
    Remove all DVD drives from VM.
    In order to just eject any ISO, Set-VMDvdDrive path should be set
    to null instead.
#>

param([String] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )
    
    $controllerNumber=$null

    # Check arguments
    if (-not $vmName) {
        "Error: Missing vmName argument"
        return $False
    }
    if (-not $hvServer) {
        "Error: Missing hvServer argument"
        return $False
    }
    # This script does not use any testParams
    $error.Clear()
    $vmGeneration = Get-VM $vmName -ComputerName $hvServer | Select-Object -ExpandProperty Generation `
        -ErrorAction SilentlyContinue
    if ($? -eq $False) {
        $vmGeneration = 1
    }

    # Make sure the DVD drive exists on the VM
    if ($vmGeneration -eq 1) {
        $controllerNumber=1
    } else {
        $controllerNumber=0
    }

    $dvdcount = $(Get-VMDvdDrive -VMName $vmName -ComputerName $hvServer).ControllerLocation.count 
    for ($i=0; $i -le $dvdcount; $i++) {
        $dvd = Get-VMDvdDrive -VMName $vmName -ComputerName $hvServer `
            -ControllerNumber $controllerNumber -ControllerLocation $i
        if ($dvd) {
            Remove-VMDvdDrive -VMName $vmName -ComputerName $hvServer `
                -ControllerNumber $controllerNumber -ControllerLocation $i
        }
    }

    if (-not $?) {
        "Error: Unable to remove the .iso from the DVD!"
        return $False
    }

    return $True
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -testParams $TestParams
