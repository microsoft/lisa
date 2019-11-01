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

param([string] $TestParams, [object] $AllVMData)

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )

    $controllerNumber=$null

    # Check arguments
    if (-not $vmName) {
        Write-LogErr "Missing vmName argument"
        return $False
    }
    if (-not $hvServer) {
        Write-LogErr "Missing hvServer argument"
        return $False
    }
    # This script does not use any testParams
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
        Write-LogErr "Unable to remove the .iso from the DVD!"
        return $False
    }

    # Get Hyper-V VHD path
    $obj = Get-WmiObject -ComputerName $hvServer -Namespace "root\virtualization\v2" -Class "MsVM_VirtualSystemManagementServiceSettingData"
    $defaultVhdPath = $obj.DefaultVirtualHardDiskPath
    if (-not $defaultVhdPath) {
        Write-LogErr "Unable to determine VhdDefaultPath on Hyper-V server ${hvServer}"
        return $False
    }
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }

    # Remove the .iso file
    $isoPath_tmp = $defaultVhdPath + "${vmName}_CDtest.iso"
    $isoPath = $isoPath_tmp.Replace(':','$')
    $isoPath = "\\" + $HvServer + "\" + $isoPath

    if (Test-Path "${isoPath}") {
        try {
            Remove-Item "${isoPath}"
        } catch {
            Write-LogErr "The .iso file $isoPath could not be removed!"
            return $False
        }
    }
    return $True
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -testParams $TestParams
