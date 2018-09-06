# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    Test-Path './heartbeat_params.info'
    if (-not $?) {
        return $True
    }
    $params = Get-Content './heartbeat_params.info' | Out-String | ConvertFrom-StringData

    if ($params.vm_name) {
        Write-Output "Info: Starting cleanup for the child VM"
        Stop-VM -Name $params.vm_name -ComputerName $params.hvServer -TurnOff
        if (-not $?) {
            LogErr "Error: Unable to Shut Down VM $vmName1"
        }

        # Delete the child VM created
        Remove-VM -Name $params.vm_name -ComputerName $params.hvServer -Confirm:$false -Force
        if (-not $?) {
            LogErr "Error: Cannot remove the child VM $vmName1"
        }
    }

    if ($params.test_vhd) {
        # Delete partition
        Dismount-VHD -Path $params.test_vhd -ComputerName $params.hvServer

        # Delete VHD
        Remove-Item $params.test_vhd -Force
    }

    Remove-Item './heartbeat_params.info' -Force
    return $True
}

Main