# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    Check the PowerPlan of all servers. If it isn't set to High Performance,
    change it.
#>
param([object] $AllVMData)
function Main {
    $retVal = $false

    # Loop through each VM
    foreach ($vmData in $allVMData) {
        # Get PowerPlan
        $powerPlanStatus = Get-CimInstance -ComputerName $vmData.HypervHost `
            -Name root\cimv2\power -Class win32_PowerPlan -Filter `
            "ElementName = 'High Performance'" | select -ExpandProperty IsActive
        if ($powerPlanStatus -eq $True) {
            Write-LogInfo "PowerPlan is on High Performance on $($vmData.HypervHost)"
            $retVal = $true
        } else {
            $startCmd = Invoke-Command -ComputerName $vmData.HypervHost -ScriptBlock {
                Start-Process powercfg.exe -ArgumentList `
                    "/setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c" `
                    -PassThru -NoNewWindow -Wait
            }
            if (-not $startCmd) {
                Write-LogErr "Failed to run the powercfg command"
            }

            $powerPlanStatus = Get-CimInstance -ComputerName $vmData.HypervHost `
                -Name root\cimv2\power -Class win32_PowerPlan -Filter `
                "ElementName = 'High Performance'" | select -ExpandProperty IsActive
            if ($powerPlanStatus -eq $True) {
                Write-LogInfo "PowerPlan was set to High Performance on $($vmData.HypervHost)"
                $retVal = $true
            }
        }
    }
    return $retVal
}

Main