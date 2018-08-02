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
    $OutputFilePath = "J:\Jenkins_Shared_Do_Not_Delete\userContent\common\VMSizes-ARM.txt"
)
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
try
{
    $ExitCode = 1
    #region Update VM sizes
    LogMsg "Getting 'Microsoft.Compute' supported region list..."
    $allRegions = (Get-AzureRmLocation | Where-Object { $_.Providers.Contains("Microsoft.Compute")} | Sort-Object).Location
    $allRegions = $allRegions | Sort-Object
    $i = 1
    $allRegions | ForEach-Object { LogMsg "$i. $_"; $i++ }
    $tab = "	"
    $RegionAndVMSize = "Region$tab`Size`n"
    foreach ( $NewRegion in $allRegions  )
    {
        $currentRegionSizes = (Get-AzureRmVMSize -Location $NewRegion).Name | Sort-Object
        if ($currentRegionSizes) 
        {
            LogMsg "Found $($currentRegionSizes.Count) sizes for $($NewRegion)..."
            $CurrentSizeCount = 1
            foreach ( $size in $currentRegionSizes )
            {
                LogMsg "|--Added $NewRegion : $CurrentSizeCount. $($size)..."
                $RegionAndVMSize += $NewRegion + $tab + $NewRegion + " " + $size + "`n"
                $CurrentSizeCount += 1
            }
        }
    }
    Set-Content -Value $RegionAndVMSize -Path $OutputFilePath -Force -NoNewline
    LogMsg "$OutputFilePath saved successfully."
    $ExitCode = 0
    #endregion
}
catch 
{
    $ExitCode = 1
    ThrowException ($_)
}
finally
{
    LogMsg "Exiting with code: $ExitCode"
    exit $ExitCode
}
#endregion