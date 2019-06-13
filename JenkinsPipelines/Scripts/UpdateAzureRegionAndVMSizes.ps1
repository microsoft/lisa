##############################################################################################
# UpdateAzureRegionAndVMSizes.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    <Description>

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Param
(
    $OutputFilePath = "J:\Jenkins_Shared_Do_Not_Delete\userContent\common\VMSizes-ARM.txt",
    $LogFileName = "UpdateAzureRegionAndVMSizes.log"
)

Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }
try
{
    $ExitCode = 1
    #region Update VM sizes
    Write-LogInfo "Getting 'Microsoft.Compute' supported region list..."
    $allRegions = (Get-AzLocation | Where-Object { $_.Providers.Contains("Microsoft.Compute")} | Sort-Object).Location
    $allRegions = $allRegions | Sort-Object
    $i = 1
    $allRegions | ForEach-Object { Write-LogInfo "$i. $_"; $i++ }
    $tab = "	"
    $RegionAndVMSize = "Region$tab`Size`n"
    foreach ( $NewRegion in $allRegions  )
    {
        $currentRegionSizes = (Get-AzVMSize -Location $NewRegion).Name | Sort-Object
        if ($currentRegionSizes)
        {
            Write-LogInfo "Found $($currentRegionSizes.Count) sizes for $($NewRegion)..."
            $CurrentSizeCount = 1
            foreach ( $size in $currentRegionSizes )
            {
                Write-LogInfo "|--Added $NewRegion : $CurrentSizeCount. $($size)..."
                $RegionAndVMSize += $NewRegion + $tab + $NewRegion + " " + $size + "`n"
                $CurrentSizeCount += 1
            }
        }
    }
    Set-Content -Value $RegionAndVMSize -Path $OutputFilePath -Force -NoNewline
    Write-LogInfo "$OutputFilePath saved successfully."
    $ExitCode = 0
    #endregion
}
catch
{
    $ExitCode = 1
    Raise-Exception ($_)
}
finally
{
    Write-LogInfo "Exiting with code: $ExitCode"
    exit $ExitCode
}
#endregion
