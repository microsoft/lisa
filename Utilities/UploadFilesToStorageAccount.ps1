##############################################################################################
# UploadFilesToStorageAccount.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    Upload files to USer Storage Account's Blob location

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE

#>
###############################################################################################

param
(
    $filePaths,
    $destinationStorageAccount,
    $destinationContainer,
    $destinationFolder,
    $destinationStorageKey
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

try
{
    if ($destinationStorageKey)
    {
        LogMsg "Using user provided storage account key."
    }
    else
    {
        LogMsg "Getting $destinationStorageAccount storage account key..."
        $allResources = Get-AzureRmResource
        $destSARG = ($allResources | Where { $_.ResourceType -imatch "storageAccounts" -and $_.ResourceName -eq "$destinationStorageAccount" }).ResourceGroupName
        $keyObj = Get-AzureRmStorageAccountKey -ResourceGroupName $destSARG -Name $destinationStorageAccount
        $destinationStorageKey = $keyObj[0].Value
    }
    $containerName = "$destinationContainer"
    $storageAccountName = $destinationStorageAccount
    $blobContext = New-AzureStorageContext -StorageAccountName $storageAccountName -StorageAccountKey $destinationStorageKey
    $UploadedFileURLs = @()
    foreach($fileName in $filePaths.Split(","))
    {
        $ticks = (Get-Date).Ticks
        #$fileName = "$LogDir\$($vmData.RoleName)-waagent.log.txt"
        $blobName = "$destinationFolder/$($fileName | Split-Path -Leaf)"
        $LocalFileProperties = Get-Item -Path $fileName
        LogMsg "Uploading $([math]::Round($LocalFileProperties.Length/1024,2))KB $filename --> $($blobContext.BlobEndPoint)$containerName/$blobName"
        $UploadedFileProperties = Set-AzureStorageBlobContent -File $filename -Container $containerName -Blob $blobName -Context $blobContext -Force -ErrorAction Stop
        if ( $LocalFileProperties.Length -eq $UploadedFileProperties.Length )
        {
            LogMsg "Succeeded."
            $UploadedFileURLs += "$($blobContext.BlobEndPoint)$containerName/$blobName"
        }
        else
        {
            LogErr "Failed."
        }
    }
    return $UploadedFileURLs
}
catch
{
    $line = $_.InvocationInfo.ScriptLineNumber
    $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
    $ErrorMessage =  $_.Exception.Message
    LogErr "EXCEPTION : $ErrorMessage"
    LogErr "Source : Line $line in script $script_name."
    LogErr "ERROR : $($blobContext.BlobEndPoint)$containerName/$blobName : Failed"
}
