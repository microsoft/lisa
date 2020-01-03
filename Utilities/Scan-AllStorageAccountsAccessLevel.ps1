##############################################################################################
# Copyright (c) Microsoft Corporation
# Licensed under the Apache License.
#
# Scan-AllStorageAccountsAccessLevel.ps1
<#
.SYNOPSIS
    This script scans the public access level of blobs or containers in all storage accounts in a subscription
    and stores the containers information which don't have private access level and can be accessed anonymously
    in .\AnonymousAccessResource.html

.PARAMETER
    -AzureSecretsFile, the path of Azure secrets file

.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE
    .\Utilities\Scan-AllStorageAccountsAccessLevel.ps1 -AzureSecretsFile <PathToSecretFile>
#>
###############################################################################################
param
(
    [String] $AzureSecretsFile,
    [string] $LogFileName = "ScanAllStorageAccountAccessLevel.log"
)

#Load libraries
if (!$global:LogFileName) {
    Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
}
Get-ChildItem ..\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

#Read secrets file and terminate if not present.
if ($AzureSecretsFile) {
    $secretsFile = $AzureSecretsFile
} elseif ($env:Azure_Secrets_File) {
    $secretsFile = $env:Azure_Secrets_File
} else {
    Write-Host "-AzureSecretsFile and env:Azure_Secrets_File are empty. Exiting."
    exit 1
}
if (Test-Path $secretsFile) {
    Write-Host "Secrets file found."
    .\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $secretsFile
} else {
    Write-Host "Secrets file not found. Exiting."
    exit 1
}

#Get subscriptionId from secret file
$SecretFileContent = Get-Content -Path $secretsFile
$SubscriptionId = $($SecretFileContent -match "SubscriptionID").Split('>')[1].Split('<')[0]

#region HTML File structure

$TableStyle = '
<style type="text/css">
  .tm  {border-collapse:collapse;border-spacing:0;border-color:#999;}
  .tm td{font-family:Arial, sans-serif;font-size:14px;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#444;background-color:#F7FDFA;}
  .tm th{font-family:Arial, sans-serif;font-size:14px;font-weight:normal;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#fff;background-color:#26ADE4;}
  .tm .tm-dk6e{font-weight:bold;color:#ffffff;text-align:center;vertical-align:top}
  .tm .tm-xa7z{background-color:#ffccc9;vertical-align:top}
  .tm .tm-ys9u{background-color:#b3ffd9;vertical-align:top}
  .tm .tm-7k3a{background-color:#D2E4FC;font-weight:bold;text-align:center;vertical-align:top}
  .tm .tm-yw4l{vertical-align:top}
  .tm .tm-6k2t{background-color:#D2E4FC;vertical-align:top}
</style>
'

$htmlHeader = '
<h2>&bull;&nbsp;SUBSCRIPTION_IDENTIFIER</h2>
<table border="0" cellpadding="0" cellspacing="0" style="border-collapse:collapse" class="tm">
  <tr>
    <th class="tm-dk6e" colspan="9">Storage Accounts with Anonymous Access</th>
  </tr>
  <tr>
    <td class="tm-7k3a">Sr</td>
    <td class="tm-7k3a">Storage Account</td>
    <td class="tm-7k3a">Container Name</td>
    <td class="tm-7k3a">Public Access Level</td>
    <td class="tm-7k3a">Location</td>
  </tr>
'

$htmlNodeRed =
'
  <tr>
    <td class="tm-yw4l">SR_ID</td>
    <td class="tm-yw4l">STORAGE_ACCOUNT</td>
    <td class="tm-yw4l">CONTAINER_NAME</td>
    <td class="tm-yw4l">PUBLIC_ACCESS_LEVEL</td>
    <td class="tm-yw4l">LOCATION</td>
  </tr>
'

$htmlEnd =
'
</table>
'
#endregion

$ReportHTMLFile = "AnonymousAccessResource.html"
if (!(Test-Path -Path ".\AnonymousAccessResource.html")) {
    $htmlHeader = $TableStyle + $htmlHeader
}

#region Get Subscription Details...
Write-Host "Running: Get-AzSubscription..."
$subscription = Get-AzSubscription -SubscriptionId $SubscriptionId
$htmlHeader = $htmlHeader.Replace("SUBSCRIPTION_IDENTIFIER","$($subscription.Name) [$($subscription.Id)]")
#endregion

#region Get all anonymous access containers and build HTML Page
$EmailSubjectTextFile = ".\ShowAnonymousAccessResourceEmailSubject.txt"
$finalHTMLString = $htmlHeader
$StorageAccountHtml = '<a href="https://ms.portal.azure.com/#resource/subscriptions/' + "$($subscription.Id)" + '/resourceGroups/RESOURCE_GROUP_NAME/providers/Microsoft.Storage/storageAccounts/STORAGE_NAME/overview" target="_blank" rel="noopener">STORAGE_NAME</a>'
$ContainerHtml = '<a href="https://ms.portal.azure.com/#blade/Microsoft_Azure_Storage/ContainerMenuBlade/overview/storageAccountId/%2Fsubscriptions%2F' + "$($subscription.Id)" + '%2FresourceGroups%2FRESOURCE_GROUP_NAME%2Fproviders%2FMicrosoft.Storage%2FstorageAccounts%2FSTORAGE_NAME/path/CONTAINER_NAME" target="_blank" rel="noopener">CONTAINER_NAME</a>'

$then = Get-Date
Write-Host "Running: Get-AzStorageAccount..."
$allStorageAccounts = Get-AzStorageAccount
$i = 0
foreach ($storage in $allStorageAccounts) {
    Write-Host "Current Storage Account: $($storage.StorageAccountName). Region: $($storage.Location)"
    Write-Host "Get-AzStorageAccountKey -ResourceGroupName $($storage.ResourceGroupName) -Name $($storage.StorageAccountName)..."
    $storageKey = (Get-AzStorageAccountKey -ResourceGroupName $storage.ResourceGroupName -Name $storage.StorageAccountName)[0].Value
    $context = New-AzStorageContext -StorageAccountName $storage.StorageAccountName -StorageAccountKey $storageKey
    Write-Host "Get-AzStorageContainer..."
    $containers = Get-AzStorageContainer -Context $context
    $containerCounter = 0
    foreach ($container in $containers) {
        $containerCounter += 1
        $publicAccess = $container.PublicAccess
        Write-Host "[Container : $containerCounter/$($containers.Count)] PublicAccess : $publicAccess..."
        if ($publicAccess -inotmatch "Off") {
            Write-Host "[Container : $containerCounter/$($containers.Count)] It can be accessed anonymously..."
            $i += 1
            $currentContainerHTMLNode = $htmlNodeRed
            $currentContainerHTMLNode = $currentContainerHTMLNode.Replace("SR_ID","$i")
            $currentStorageHTMLLink = $StorageAccountHtml.Replace("RESOURCE_GROUP_NAME","$($storage.ResourceGroupName)").Replace("STORAGE_NAME","$($storage.StorageAccountName)")
            $currentContainerHTMLLink = $ContainerHtml.Replace("RESOURCE_GROUP_NAME","$($storage.ResourceGroupName)").Replace("STORAGE_NAME","$($storage.StorageAccountName)").Replace("CONTAINER_NAME","$($container.Name)")
            $currentContainerHTMLNode = $currentContainerHTMLNode.Replace("STORAGE_ACCOUNT","$currentStorageHTMLLink")
            $currentContainerHTMLNode = $currentContainerHTMLNode.Replace("CONTAINER_NAME","$currentContainerHTMLLink")
            $currentContainerHTMLNode = $currentContainerHTMLNode.Replace("PUBLIC_ACCESS_LEVEL","$publicAccess")
            $currentContainerHTMLNode = $currentContainerHTMLNode.Replace("LOCATION","$($storage.Location)")
            $finalHTMLString += $currentContainerHTMLNode
        }
    }
}
$finalHTMLString += $htmlEnd

$ElapsedTime = $($(Get-Date) - $then)
Write-Host "Elapsed Time: $($ElapsedTime.Hours) hours $($ElapsedTime.Minutes) minutes $($ElapsedTime.Seconds) seconds"
Add-Content -Value $finalHTMLString -Path $ReportHTMLFile
Set-Content -Path $EmailSubjectTextFile -Value "Azure Subscription Storage Accounts Security Report: $($psttime.Year)/$($psttime.Month)/$($psttime.Day)"
Write-Host "Anonymous access resources report is ready."

#endregion
