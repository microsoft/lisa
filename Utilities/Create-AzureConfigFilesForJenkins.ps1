# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
<#
.SYNOPSIS
    This file creates 'Property Files' for jenkins dynamic menu creation.
    These 'Property Files' can be used to create dynamic jenkins menus using parameter type - "Extended Choice Parameter".

.PARAMETER
	See source code for the detailed parameters

.NOTES
	PREREQUISITES:
	1) You should have a valid Azure subscription and read access.

.EXAMPLE
	Example 1 :
    .\Utilities\Create-AzureConfigFilesForJenkins.ps1
	Example 2 :
    .\Utilities\Create-AzureConfigFilesForJenkins.ps1 -SecretFilePath .\AzureSecretFile.xml `
        -ImageLocation "northeurope" `
        -ImagePublishers "Canonical,SUSE"
#>

param (
    [string] $SecretFilePath = "",
    [string] $ImageLocation = "westus2",
    [string] $ImagePublishers = "Canonical,SUSE,Oracle,CoreOS,RedHat,OpenLogic,credativ,kali-linux,clear-linux-project,MicrosoftOSTC,MicrosoftRServer,MicrosoftSharePoint,MicrosoftSQLServer,MicrosoftVisualStudio,MicrosoftWindowsServer,MicrosoftWindowsServerEssentials,MicrosoftWindowsServerHPCPack,MicrosoftWindowsServerRemoteDesktop"
)

#region Authenticate the powershell session.
if ($SecretFilePath) {
    .\Utilities\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $SecretFilePath
} else {
    Write-Host "Secret File not provided. Checking subscriptions..."
    $Subscriptions = Get-AzSubscription
    if ($Subscriptions) {
        $SelectedSubscription = Select-AzSubscription -Subscription $Subscriptions[0].Id
        Write-Host "Selected $($SelectedSubscription.Name)"
    } else {
        Write-Host "Powershell Session is not authenticated / User doesn't have access to any subscription. Exiting."
        exit 1
    }
}
#endregion

# Initialize variables.
$tab = "	"

# Output filepaths.
$AzureImagesFilePath = ".\Azure-MarketPlace-Images.txt"
$AzureLatestImagesFilePath = ".\Azure-MarketPlace-Latest-Images.txt"
$AzureRegionSizeFilePath = ".\Azure-Region-And-VMSizes.txt"
$AzureRegionFilePath = ".\Azure-Regions.txt"
$AzureVMSizeFilePath = ".\Azure-VMSizes.txt"

# Initialize the variables for fail-safe.
$ImageAdded = $false
$SizeRegionAdded = $false

# DO NOT MODIFY BELOW VARIABLES.
$AzureVMImagesString = "Publisher	Offer	SKU	Version`n"
$AzureLatestVMImagesString = "Image="
$AzureRegionsString = "Region="
$AzureSizeString = "Size="
$AzureRegionSizeString = "Region	Size`n"

#region Collect Market place Images.
try {
    foreach ( $newPub in $ImagePublishers.Split(",") ) {
        $offers = Get-AzVMImageOffer -PublisherName $newPub -Location $ImageLocation
        if ($offers) {
            Write-Host "Found $($offers.Count) offers for $($newPub)..."
            foreach ( $offer in $offers ) {
                $SKUs = Get-AzVMImageSku -Location $ImageLocation -PublisherName $newPub -Offer $offer.Offer -ErrorAction SilentlyContinue
                Write-Host "|--Found $($SKUs.Count) SKUs for $($offer.Offer)..."
                foreach ( $SKU in $SKUs ) {
                    $isLatestAdded = $false
                    $rmImages = Get-AzVMImage -Location $ImageLocation -PublisherName $newPub -Offer $offer.Offer -Skus $SKU.Skus
                    Write-Host "|--|--Found $($rmImages.Count) Images for $($SKU.Skus)..."
                    foreach ( $rmImage in $rmImages ) {
                        if ( $isLatestAdded ) {
                            Write-Host "|--|--|--Added Version $($rmImage.Version)..."
                            $AzureVMImagesString += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + $rmImage.Version + "`n"
                            $ImageAdded = $true
                        }
                        else {
                            Write-Host "|--|--|--Added Generalized version: latest..."
                            $AzureVMImagesString += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + "latest" + "`n"
                            $AzureLatestVMImagesString += $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + "latest" + ","
                            Write-Host "|--|--|--Added Version $($rmImage.Version)..."
                            $AzureVMImagesString += $newPub + $tab + $offer.Offer + $tab + $SKU.Skus + $tab + $newPub + " " + $offer.Offer + " " + $SKU.Skus + " " + $rmImage.Version + "`n"
                            $isLatestAdded = $true
                            $ImageAdded = $true
                        }
                    }
                }
            }
        }
    }

    if ($ImageAdded) {
        $AzureLatestVMImagesString = $AzureLatestVMImagesString.TrimEnd(",")
        $AzureVMImagesString = $AzureVMImagesString.TrimEnd("`n")
        Write-Host "Images data collection succeeded."
        Write-Host "Updating $AzureImagesFilePath..."
        Set-Content -Value $AzureVMImagesString -Path $AzureImagesFilePath -Force
        Write-Host "Updating $AzureLatestImagesFilePath..."
        Set-Content -Value $AzureLatestVMImagesString -Path $AzureLatestImagesFilePath -Force
    } else {
        Write-Host "Images data collection failed. Azure configs files are not changed."
    }
}
catch {
    Write-Host "Exception in fetching the Images. Azure configs files are not changed."
}
#endregion


#region Collect Region and VM size
try {
    $AllSizes = @()
    $allRegions = (Get-AzLocation | Where-Object { $_.Providers -imatch "Microsoft.Compute" `
        -and $_.Providers -imatch "Microsoft.Storage" -and $_.Providers -imatch "Microsoft.Network"}).location | Sort-Object
    foreach ( $newRegion in $allRegions  ) {
        $AzureRegionsString += "$newRegion,"
        $currentRegionSizes = (Get-AzVMSize -Location $newRegion -ErrorAction SilentlyContinue).Name | Sort-Object
        if ($currentRegionSizes) {
            Write-Host "Found $($currentRegionSizes.Count) sizes for $($newRegion)..."
            foreach ( $size in $currentRegionSizes ) {
                $AllSizes += $size
                Write-Host "|--Added $newRegion : $($size)..."
                $AzureRegionSizeString += $newRegion + $tab + $newRegion + " " + $size + "`n"
                $SizeRegionAdded = $true
            }
        }
    }
    if ($AllSizes) {
        $AllSizes = $AllSizes | Sort-Object | Get-Unique -ErrorAction SilentlyContinue
        foreach ($size in $AllSizes) {
            Write-Host "|--Added $newRegion : $($size)..."
            $AzureSizeString += $size + ","
        }
    }
    if ($SizeRegionAdded) {
        $AzureRegionSizeString = $AzureRegionSizeString.TrimEnd("`n")
        $AzureRegionsString = $AzureRegionsString.TrimEnd(",")
        $AzureSizeString = $AzureSizeString.TrimEnd(",")
        Write-Host "Region / Size data collection succeeded.."
        Write-Host "Updating $AzureRegionSizeFilePath..."
        Set-Content -Value $AzureRegionSizeString -Path $AzureRegionSizeFilePath -Force
        Write-Host "Updating $AzureRegionFilePath..."
        Set-Content -Value $AzureRegionsString -Path $AzureRegionFilePath -Force
        Write-Host "Updating $AzureVMSizeFilePath..."
        Set-Content -Value $AzureSizeString -Path $AzureVMSizeFilePath -Force
    }
    else {
        Write-Host "Region / Size data collection failed. Azure configs files are not changed."
    }
}
catch {
    Write-Host "Exception in fetching the Region / Size data. Azure configs files are not changed."
}
#endregion
