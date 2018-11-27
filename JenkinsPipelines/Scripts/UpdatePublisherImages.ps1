##############################################################################################
# UpdatePublisherImages.ps1
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
    $OutputFilePath = "J:\Jenkins_Shared_Do_Not_Delete\userContent\common\VMImages-ARM.txt",
    $Publishers = "Canonical,SUSE,Oracle,CoreOS,RedHat,OpenLogic,credativ,kali-linux,clear-linux-project",
    $LogFileName = "UpdatePublisherImages.log"
)

Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }
try
{
    $ExitCode = 1
    #region Update All ARM Images
    $tab = "	"
    $Location = "northeurope"
    $allRMPubs = $Publishers.Split(",") | Sort-Object
    $ARMImages = "Publisher	Offer	SKU	Version`n"
    foreach ( $newPub in $allRMPubs )
    {
        $offers = Get-AzureRmVMImageOffer -PublisherName $newPub -Location $Location
        if ($offers)
        {
            Write-LogInfo "Found $($offers.Count) offers for $($newPub)..."
            foreach ( $offer in $offers )
            {
                $SKUs = Get-AzureRmVMImageSku -Location $Location -PublisherName $newPub -Offer $offer.Offer -ErrorAction SilentlyContinue
                Write-LogInfo "|--Found $($SKUs.Count) SKUs for $($offer.Offer)..."
                foreach ( $SKU in $SKUs )
                {
                    $rmImages = Get-AzureRmVMImage -Location $Location -PublisherName $newPub -Offer $offer.Offer -Skus $SKU.Skus
                    Write-LogInfo "|--|--Found $($rmImages.Count) Images for $($SKU.Skus)..."
                    if ( $rmImages.Count -gt 1 )
                    {
                        $isLatestAdded = $false
                    }
                    else
                    {
                        $isLatestAdded = $true
                    }
                    foreach ( $rmImage in $rmImages )
                    {
                        if ( $isLatestAdded )
                        {
                            Write-LogInfo "|--|--|--Added Version $($rmImage.Version)..."
                            $ARMImages += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + $rmImage.Version + "`n"
                        }
                        else
                        {
                            Write-LogInfo "|--|--|--Added Generalized version: latest..."
                            $ARMImages += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + "latest" + "`n"
                            Write-LogInfo "|--|--|--Added Version $($rmImage.Version)..."
                            $ARMImages += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + $rmImage.Version + "`n"
                            $isLatestAdded = $true
                        }
                    }
                }
            }
        }
    }
    $ARMImages = $ARMImages.TrimEnd("`n")
    Write-LogInfo "Creating file $OutputFilePath..."
    Set-Content -Value $ARMImages -Path $OutputFilePath -Force -NoNewline
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
