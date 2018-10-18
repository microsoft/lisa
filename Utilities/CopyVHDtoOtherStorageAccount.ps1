##############################################################################################
# CopyVHDtoOtherStorageAccounts.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    This script copies VHD file to another storage account.

.PARAMETER

.INPUTS

.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE
#>
###############################################################################################

param
(
    [string]$sourceLocation,
    [string]$destinationLocations,
    [string]$destinationAccountType,
    [string]$sourceVHDName,
    [string]$destinationVHDName
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

try
{
    if (!$destinationVHDName)
    {
        $destinationVHDName = $sourceVHDName
    }
    if (!$destinationAccountType)
    {
        $destinationAccountType="Standard,Premium"
    }

    $RegionName = $sourceLocation.Replace(" ","").Replace('"',"").ToLower()
    $RegionStorageMapping = [xml](Get-Content .\XML\RegionAndStorageAccounts.xml)
    $SourceStorageAccountName = $RegionStorageMapping.AllRegions.$RegionName.StandardStorage

    #region Collect current VHD, Storage Account and Key
    $saInfoCollected = $false
    $retryCount = 0
    $maxRetryCount = 999
    while(!$saInfoCollected -and ($retryCount -lt $maxRetryCount))
    {
        try
        {
            $retryCount += 1
            LogMsg "[Attempt $retryCount/$maxRetryCount] : Getting Storage Account details ..."
            $GetAzureRMStorageAccount = $null
            $GetAzureRMStorageAccount = Get-AzureRmStorageAccount
            if ($GetAzureRMStorageAccount -eq $null)
            {
                $saInfoCollected = $false
            }
            else
            {
                $saInfoCollected = $true
            }
        }
        catch
        {
            LogErr "Error in fetching Storage Account info. Retrying in 10 seconds."
            sleep -Seconds 10
            $saInfoCollected = $false
        }
    }
    #endregion

    $currentVHDName = $sourceVHDName
    $testStorageAccount = $SourceStorageAccountName
    $testStorageAccountKey = (Get-AzureRmStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$testStorageAccount"}).ResourceGroupName) -Name $testStorageAccount)[0].Value

    $targetRegions = (Get-AzureRmLocation).Location
    if ($destinationLocations)
    {
        $targetRegions = $destinationLocations.Split(",")
    }
    else
    {
        $targetRegions = (Get-AzureRmLocation).Location
    }
    $targetStorageAccounts = @()
    foreach ($newRegion in $targetRegions)
    {
        if ( $destinationAccountType -imatch "Standard")
        {
            $targetStorageAccounts +=  $RegionStorageMapping.AllRegions.$newRegion.StandardStorage
        }
        if ( $destinationAccountType -imatch "Premium")
        {
            $targetStorageAccounts +=  $RegionStorageMapping.AllRegions.$newRegion.PremiumStorage
        }
    }
    $destContextArr = @()
    foreach ($targetSA in $targetStorageAccounts)
    {
        #region Copy as Latest VHD
        [string]$SrcStorageAccount = $testStorageAccount
        [string]$SrcStorageBlob = $currentVHDName
        $SrcStorageAccountKey = $testStorageAccountKey
        $SrcStorageContainer = "vhds"

        [string]$DestAccountName =  $targetSA
        [string]$DestBlob = $destinationVHDName
        $DestAccountKey= (Get-AzureRmStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$targetSA"}).ResourceGroupName) -Name $targetSA)[0].Value
        $DestContainer = "vhds"
        $context = New-AzureStorageContext -StorageAccountName $srcStorageAccount -StorageAccountKey $srcStorageAccountKey
        $expireTime = Get-Date
        $expireTime = $expireTime.AddYears(1)
        $SasUrl = New-AzureStorageBlobSASToken -container $srcStorageContainer -Blob $srcStorageBlob -Permission R -ExpiryTime $expireTime -FullUri -Context $Context

        #
        # Start Replication to DogFood
        #

        $destContext = New-AzureStorageContext -StorageAccountName $destAccountName -StorageAccountKey $destAccountKey
        $testContainer = Get-AzureStorageContainer -Name $destContainer -Context $destContext -ErrorAction Ignore
        if ($testContainer -eq $null) {
            New-AzureStorageContainer -Name $destContainer -context $destContext
        }
        # Start the Copy
        if (($SrcStorageAccount -eq $DestAccountName) -and ($SrcStorageBlob -eq $DestBlob))
        {
            LogMsg "Skipping copy for : $DestAccountName as source storage account and VHD name is same."
        }
        else
        {
            LogMsg "Copying $SrcStorageBlob as $DestBlob from and to storage account $DestAccountName/$DestContainer"
            $out = Start-AzureStorageBlobCopy -AbsoluteUri $SasUrl  -DestContainer $destContainer -DestContext $destContext -DestBlob $destBlob -Force
            $destContextArr += $destContext
        }
    }
    #
    # Monitor replication status
    #
    $CopyingInProgress = $true
    while($CopyingInProgress)
    {
        $CopyingInProgress = $false
        $newDestContextArr = @()
        foreach ($destContext in $destContextArr)
        {
            $status = Get-AzureStorageBlobCopyState -Container $destContainer -Blob $destBlob -Context $destContext
            if ($status.Status -eq "Success")
            {
                LogMsg "$DestBlob : $($destContext.StorageAccountName) : Done : 100 %"
            }
            elseif ($status.Status -eq "Failed")
            {
                LogMsg "$DestBlob : $($destContext.StorageAccountName) : Failed."
            }
            elseif ($status.Status -eq "Pending")
            {
                sleep -Milliseconds 100
                $CopyingInProgress = $true
                $newDestContextArr += $destContext
                $copyPercent = [math]::Round((($status.BytesCopied/$status.TotalBytes) * 100),2)
                LogMsg "$DestBlob : $($destContext.StorageAccountName) : Running : $copyPercent %"
            }
        }
        if ($CopyingInProgress)
        {
            LogMsg "--------$($newDestContextArr.Count) copy operations still in progress.-------"
            $destContextArr = $newDestContextArr
            Sleep -Seconds 10
        }
        $ExitCode = 0
    }
    LogMsg "All Copy Operations completed successfully."
}
catch 
{
    $ExitCode = 1
    ThrowExcpetion ($_)
}
finally
{
    LogMsg "Exiting with code: $ExitCode"
    exit $ExitCode
}
#endregion