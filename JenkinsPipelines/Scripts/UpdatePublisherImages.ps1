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
    $Publishers = "Canonical,SUSE,Oracle,CoreOS,RedHat,OpenLogic,credativ,kali-linux,clear-linux-project"
)
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
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
            LogMsg "Found $($offers.Count) offers for $($newPub)..."
            foreach ( $offer in $offers )
            {
                $SKUs = Get-AzureRmVMImageSku -Location $Location -PublisherName $newPub -Offer $offer.Offer -ErrorAction SilentlyContinue
                LogMsg "|--Found $($SKUs.Count) SKUs for $($offer.Offer)..."
                foreach ( $SKU in $SKUs )
                {
                    $rmImages = Get-AzureRmVMImage -Location $Location -PublisherName $newPub -Offer $offer.Offer -Skus $SKU.Skus
                    LogMsg "|--|--Found $($rmImages.Count) Images for $($SKU.Skus)..."
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
                            LogMsg "|--|--|--Added Version $($rmImage.Version)..."
                            $ARMImages += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + $rmImage.Version + "`n"
                        }
                        else
                        {
                            LogMsg "|--|--|--Added Generalized version: latest..."
                            $ARMImages += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + "latest" + "`n"
                            LogMsg "|--|--|--Added Version $($rmImage.Version)..."
                            $ARMImages += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + $rmImage.Version + "`n"
                            $isLatestAdded = $true
                        }
                    }
                }
            }
        }
    }
    $ARMImages = $ARMImages.TrimEnd("`n")
    LogMsg "Creating file $OutputFilePath..."
    Set-Content -Value $ARMImages -Path $OutputFilePath -Force -NoNewline
    LogMsg "$OutputFilePath Saved successfully."
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