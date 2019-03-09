# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    Enable the nested virtualization.
#>

param([object] $AllVMData)

function Main {
    $retVal = $true

    foreach ($vmData in $allVMData) {
        Write-LogInfo "Enable nested virtualization for $($vmData.RoleName) on $($vmData.HypervHost) host."
        Set-VMProcessor -VMName $vmData.RoleName -ExposeVirtualizationExtensions $true -ComputerName $vmData.HypervHost
        Set-VMNetworkAdapter -VMName $vmData.RoleName -MacAddressSpoofing on -ComputerName $vmData.HypervHost
        if ( $? ) {
            Write-LogInfo "Succeeded."
        } else {
            $retVal = $false
            Write-LogErr "Enable nested virtualization for $($vmData.RoleName) on $($vmData.HypervHost) failed."
        }
    }

    return $retVal
}

Main