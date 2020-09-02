##############################################################################################
# UploadVHDtoAzureStorage.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Description :
# Operations :
#
###############################################################################################

Param
(

    #Mandatory parameters
    [string]$VHDPath="",
    [string]$StorageAccount="ExistingStorage_Standard",
    [string]$Region="westus2",
    [string] $LogFileName = "UploadVHDtoAzureStorage.log",
    #Optional parameters
    [int]$NumberOfUploaderThreads=16,
    [switch]$DeleteVHDAfterUpload=$false
)

if (!$global:LogFileName){
    Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
}
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

$regionStorageMapping = [xml](Get-Content "$PSScriptRoot\..\XML\RegionAndStorageAccounts.xml")
if ($StorageAccount) {
	if ($StorageAccount -imatch "^ExistingStorage_Standard") {
		$StorageAccountName = $regionStorageMapping.AllRegions.$Region.StandardStorage
	}
	elseif ($StorageAccount -imatch "^ExistingStorage_Premium") {
		$StorageAccountName = $regionStorageMapping.AllRegions.$Region.PremiumStorage
	}
}
else {
	$StorageAccountName = $regionStorageMapping.AllRegions.$Region.StandardStorage
}

$ExitCode = 1
try
{
    Write-LogInfo "Target storage account: $StorageAccountName"
    Write-LogInfo "Gettting Resource group name of the Storage account - $StorageAccountName"
    $StorageAccountNameRG = (Get-AzResource | Where { $_.Name -eq $StorageAccountName}).ResourceGroupName
    $UploadLink  = "https://$StorageAccountName.blob.core.windows.net/vhds"

    Write-LogInfo "WARNING: If a VHD is present in storage account with same name, it will be overwritten."

    $RetryUpload = $true
    $retryCount = 0
    $VHDName = $VHDPath | Split-Path -Leaf
    while($RetryUpload -and ($retryCount -le 10))
    {
        $retryCount += 1
        Write-LogInfo "Initiating '$VHDPath' upload to $UploadLink. Please wait..."
        $out = Add-AzVhd -ResourceGroupName $StorageAccountNameRG -Destination "$UploadLink/$VHDName" -LocalFilePath "$VHDPath" -NumberOfUploaderThreads $NumberOfUploaderThreads -OverWrite -Verbose
        $uploadStatus = $?
        if ( $uploadStatus )
        {
            Write-LogInfo "Upload successful."
            Write-LogInfo "$($out.DestinationUri)"
            $ExitCode = 0
            $RetryUpload = $false
            if ($DeleteVHDAfterUpload)
            {
                Write-LogInfo "Deleting $VHDPath"
                $out = Remove-Item -Path $VHDPath -Force | Out-Null
            }
            else
            {
                Write-LogInfo "Skipping cleanup of $VHDPath"
            }
            Write-LogInfo "Saving VHD URL to .\UploadedVHDLink.azure.env"
            Set-Content -Value $($out.DestinationUri) -Path .\UploadedVHDLink.azure.env -Force -Verbose -NoNewline
        }
        else
        {
            Write-LogWarn "Something went wrong in upload. Retrying..."
            $RetryUpload = $true
            Start-Sleep -Seconds 10
        }
    }
}

catch
{
    Raise-Exception($_)
}
finally
{
    Write-LogInfo "Exiting with code : $ExitCode"
    exit $ExitCode
}


