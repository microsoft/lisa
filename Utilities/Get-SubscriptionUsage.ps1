# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation

# Description: This script creates an HTML report of our subscription usage details at .\SubscriptionUsage.html and .\ShowSubscriptionUsageEmailSubject.txt

param
(
    [switch] $UseSecretsFile,
    [switch] $UploadToDB,
    [string] $LogFileName = "GetSubscriptionUsage.log",
    $AzureSecretsFile
)

#Load libraries
if (!$global:LogFileName) {
    Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
}
Get-ChildItem ..\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

#When given -UseSecretsFile or an AzureSecretsFile path, we will attempt to search the path or the environment variable.
if ($UseSecretsFile -or $AzureSecretsFile) {
    #Read secrets file and terminate if not present.
    if ($AzureSecretsFile) {
        $secretsFile = $AzureSecretsFile
    } elseif ($env:Azure_Secrets_File) {
        $secretsFile = $env:Azure_Secrets_File
    } else {
        Write-LogInfo "-AzureSecretsFile and env:Azure_Secrets_File are empty. Exiting."
        exit 1
    }
    if (Test-Path $secretsFile) {
        Write-LogInfo "Secrets file found."
        .\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $secretsFile
        $xmlSecrets = [xml](Get-Content $secretsFile)
    } else {
        Write-LogInfo "Secrets file not found. Exiting."
        exit 1
    }
}

Function Get-StorageAccountUsage ($storageAccountObject) {
    $LockedStandardUsage = 0
    $LockedPremiumUsage = 0
    $UnlockedStandardUsage = 0
    $UnlockedPremiumUsage = 0
    Write-LogInfo "Current Storage Account: $($StorageAccountObject.StorageAccountName). Region: $($StorageAccountObject.Location)"
    Write-LogInfo "Get-AzStorageAccountKey -ResourceGroupName $($StorageAccountObject.ResourceGroupName) -Name $($StorageAccountObject.StorageAccountName)..."
    $storageKey = (Get-AzStorageAccountKey -ResourceGroupName $StorageAccountObject.ResourceGroupName -Name $StorageAccountObject.StorageAccountName)[0].Value
    $context = New-AzStorageContext -StorageAccountName $StorageAccountObject.StorageAccountName -StorageAccountKey $storageKey
    Write-LogInfo "Get-AzStorageContainer..."
    $containers = Get-AzStorageContainer -Context $context -ConcurrentTaskCount 64 | Where-Object { $_.Name -inotmatch "bootdiagnostics-" }
    $containerCounter = 0
    foreach ($container in $containers) {
        $containerCounter += 1
        Write-LogInfo "[Container : $containerCounter/$($containers.Count)]. Get-AzStorageBlob -Container $($container.Name) ..."
        $blobs = Get-AzStorageBlob -Container $($container.Name) -Context $context -ConcurrentTaskCount 64
        foreach ($blob in $blobs) {
            if ($blob.ICloudBlob.Properties.LeaseStatus -eq 'Unlocked') {
                if ($storageAccountObject.Sku.Tier -imatch "Premium") {
                    $UnlockedPremiumUsage += $blob.Length
                } elseif ($storageAccountObject.Sku.Tier -imatch "Standard") {
                    $UnlockedStandardUsage += $blob.Length
                }
            } else {
                if ($storageAccountObject.Sku.Tier -imatch "Premium") {
                    $LockedPremiumUsage += $blob.Length
                } elseif ($storageAccountObject.Sku.Tier -imatch "Standard") {
                    $LockedStandardUsage += $blob.Length
                }
            }
        }
    }
    if ($UnlockedPremiumUsage -ne 0) {
        $UnlockedPremiumUsage = [math]::Round($UnlockedPremiumUsage / 1GB, 0)
    }
    if ($UnlockedStandardUsage -ne 0) {
        $UnlockedStandardUsage = [math]::Round($UnlockedStandardUsage / 1GB, 0)
    }
    if ($LockedPremiumUsage -ne 0) {
        $LockedPremiumUsage = [math]::Round($LockedPremiumUsage / 1GB, 0)
    }
    if ($LockedStandardUsage -ne 0) {
        $LockedStandardUsage = [math]::Round($LockedStandardUsage / 1GB, 0)
    }
    return $LockedStandardUsage, $LockedPremiumUsage, $UnlockedStandardUsage, $UnlockedPremiumUsage
}

Function Get-ManagedDiskUsage ($ManagedDiskObject) {
    $LockedStandardUsage = 0
    $LockedPremiumUsage = 0
    $UnlockedStandardUsage = 0
    $UnlockedPremiumUsage = 0
    if ($ManagedDiskObject.DiskState -eq 'Attached') {
        if ($ManagedDiskObject.Sku.Tier -imatch "Premium") {
            $LockedPremiumUsage += [math]::Round($ManagedDiskObject.DiskSizeGB, 0)
        } elseif ($ManagedDiskObject.Sku.Tier -imatch "Standard") {
            $LockedStandardUsage += [math]::Round($ManagedDiskObject.DiskSizeGB, 0)
        }
    } else {
        if ($ManagedDiskObject.Sku.Tier -imatch "Premium") {
            $UnlockedPremiumUsage += [math]::Round($ManagedDiskObject.DiskSizeGB, 0)
        } elseif ($ManagedDiskObject.Sku.Tier -imatch "Standard") {
            $UnlockedStandardUsage += [math]::Round($ManagedDiskObject.DiskSizeGB, 0)
        }
    }
    return $LockedStandardUsage, $LockedPremiumUsage, $UnlockedStandardUsage, $UnlockedPremiumUsage
}

try {
    $allVMStatus = @()
    $EmailSubjectTextFile = ".\ShowSubscriptionUsageEmailSubject.txt"
    $FinalHtmlFile = ".\SubscriptionUsage.html"
    $pstzone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Pacific Standard Time")
    $psttime = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $pstzone)
    Write-LogInfo "Running: Get-AzLocation..."
    $allRegions = (Get-AzLocation | Where-Object { $_.Providers -imatch "Microsoft.Compute" }).Location | Sort-Object
    foreach ($region in $allRegions) {
        Write-LogInfo "Running: Get-AzVM -Status -Location $region"
        $allVMStatus += Get-AzVM -Status -Location $region -ErrorAction SilentlyContinue
    }
    Write-LogInfo "Running: Get-AzSubscription..."
    $subscription = Get-AzSubscription -SubscriptionId $xmlSecrets.secrets.SubscriptionID
    Write-LogInfo "Running: Get-AzResource..."
    $allResources = Get-AzResource

    Write-LogInfo "Running: Get-AzStorageAccount..."
    $allStorageAccounts = Get-AzStorageAccount

    Write-LogInfo "Running: Get-AzDisk..."
    $allManagedDisks = Get-AzDisk

} catch {
    Write-LogInfo "Error while fetching data. Please try again."
    Add-Content -Path $FinalHtmlFile -Value "There was some error in fetching data from Azure today."
    Set-Content -Path $EmailSubjectTextFile -Value "Azure Subscription Daily Utilization Report: $($psttime.Year)/$($psttime.Month)/$($psttime.Day)"
    exit 1
}

#region HTML file header
$TableStyle = '
<style type="text/css">
.tg  {border-collapse:collapse;border-spacing:0;border-color:#999;}
.tg td{font-family:Arial, sans-serif;font-size:14px;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#444;background-color:#F7FDFA;}
.tg th{font-family:Arial, sans-serif;font-size:14px;font-weight:normal;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#fff;background-color:#26ADE4;}
.tg .tg-baqh{text-align:left;vertical-align:top}
.tg .tg-lqy6{text-align:right;vertical-align:top}
.tg .tg-lqy6bold{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-yw4l{vertical-align:top}
.tm .tm-7k3a{background-color:#D2E4FC;font-weight:bold;text-align:center;vertical-align:top}
.tg .tg-amwm{color:#000000;;background-color:#D2E4FC;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-amwmleft{color:#000000;background-color:#D2E4FC;text-align:left;font-weight:bold;vertical-align:top}
.tg .tg-amwmcenter{text-align:center;font-weight:bold;vertical-align:top}
.tg .tg-amwmred{color:#fe0000;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-amwmgreen{color:#036400;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-9hbo{font-weight:bold;vertical-align:top}
.tg .tg-l2oz{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-l2ozred{color:#fe0000;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-l2ozgreen{color:#036400;font-weight:bold;text-align:right;vertical-align:top}
</style>
'
$htmlFileStart = '
POWERBI_MESSAGE
'
if (!(Test-Path -Path ".\SubscriptionUsage.html")) {
    $htmlFileStart = $TableStyle + $htmlFileStart
    $htmlFileStart = $htmlFileStart.Replace("POWERBI_MESSAGE", '<p style="text-align: left;"><em>Last refreshed&nbsp;<strong>DATE_TIME. </strong></em> <a href="https://msit.powerbi.com/groups/bf12e64a-dd80-4fa8-8297-6607ea85f687/reports/251e1a2b-1568-4d4d-9daa-0ca47a20162b/ReportSection" target="_blank" rel="noopener"><em><strong>Click Here</strong></em></a> to see the report in PowerBI.</p>')
} else {
    $htmlFileStart = $htmlFileStart.Replace("POWERBI_MESSAGE", '<hr />')
}

$htmlFileStart = $htmlFileStart.Replace("DATE_TIME", "$($psttime.DateTime) PST")
#endregion

#region HTML File row
$htmlFileRow = '
  <tr>
    <td class="tg-yw4l">Current_Serial</td>
    <td class="tg-baqh">Current_Region</td>
    <td class="tg-lqy6">Region_VMs</td>
    <td class="tg-lqy6">Region_Used_Cores / Region_Deallocated_Cores / Region_Allowed_Cores</td>
    <td class="CORE_CLASS">Region_Core_Percent</td>
    <td class="tg-lqy6">Region_SA</td>
    <td class="tg-lqy6">Current_Overall_Storage_GB</td>
    <td class="tg-lqy6">Region_PublicIP</td>
    <td class="tg-lqy6">Region_VNET</td>
  </tr>
'
#endregion

#region HTML File footer
$htmlFileSummary = '
  <tr>
    <td class="tg-9hbo"></td>
    <td class="tg-lqy6bold">Total</td>
    <td class="tg-l2oz">Total_VMs</td>
    <td class="tg-l2oz">Total_Used_Cores / Total_Deallocated_Cores / Total_Allowed_Cores</td>
    <td class="CORE_CLASS">Total_Core_Percent</td>
    <td class="tg-l2oz">Total_SA/Allowed_SA</td>
    <td class="tg-l2oz">Total_Overall_Storage_GB</td>
    <td class="tg-l2oz">Total_PublicIP</td>
    <td class="tg-l2oz">Total_VNET</td>
  </tr>
'
#endregion

$storage_String = "Microsoft.Storage/storageAccounts"
$VM_String = "Microsoft.Compute/virtualMachines"
$VNET_String = "Microsoft.Network/virtualNetworks"
$PublicIP_String = "Microsoft.Network/publicIPAddresses"
$ManagedDisk_String = "Microsoft.Compute/disks"

$regionCounter = 0
$totalVMs = 0
$totalVNETs = 0
$totalPublicIPs = 0
$totalUsedCores = 0
$totalAllowedCores = 0
$totalDeallocatedCores = 0
$totalStorageAccounts = 0
$totalStandardLockedStorageUsageInGB = 0
$totalPremiumLockedStorageUsageInGB = 0
$totalStandardUnlockedStorageUsageInGB = 0
$totalPremiumUnlockedStorageUsageInGB = 0
#region Create HTML report

$ReportHeader = '
<table class="tg">
  <tr>
      <th class="tg-amwmcenter" colspan="9">Resource Usage</th>
  </tr>
  <tr>
    <th class="tg-amwmleft">SR. #</th>
    <th class="tg-amwmleft">Region</th>
    <th class="tg-amwm">Total VMs</th>
    <th class="tg-amwm">vCPU Cores (Used / Deallocated / Max Allowed)</th>
    <th class="tg-amwm">vCPU Core usage %</th>
    <th class="tg-amwm">Storage Accounts</th>
    <th class="tg-amwm">Total Storage Usage (GB)</th>
    <th class="tg-amwm">Public IPs</th>
    <th class="tg-amwm">Virtual Networks</th>
  </tr>
  '


$ReportHeader = $ReportHeader.Replace("SUBSCRIPTION_IDENTIFIER", "$($subscription.Name)[$($subscription.Id)]")
$UsageReport = $ReportHeader

$UsageReport += "FINAL_SUMMARY"

if ($UploadToDB) {
    $dataSource = $xmlSecrets.secrets.DatabaseServer
    $user = $xmlSecrets.secrets.DatabaseUser
    $password = $xmlSecrets.secrets.DatabasePassword
    $database = $xmlSecrets.secrets.DatabaseName
    $dataTableName = "SubscriptionUsage"
    $connectionString = "Server=$dataSource;uid=$user; pwd=$password;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    $SQLQuery = "INSERT INTO $dataTableName (SubscriptionID,SubscriptionName,Region,DateAndTime,TotalVMs,vCPUAllocated,vCPUDeAllocated,vCPUTotal,vCPUMaxAllowed,vCPUPercentUsed,StandardLockedStorageSizeInGB,StandardUnlockedStorageSizeInGB,PremiumLockedStorageSizeInGB,PremiumUnlockedStorageSizeInGB,TotalStorages,PublicIPs,VirtualNetworks) VALUES "
}

foreach ($region in $allRegions) {
    $currentHTMLNode = $htmlFileRow
    $currentVMs = 0
    $currentVNETs = 0
    $currentPublicIPs = 0
    $currentUsedCores = 0
    $currentDeallocatedCores = 0
    $currentStorageAccounts = 0
    $currentStandardLockedStorageUsageInGB = 0
    $currentPremiumLockedStorageUsageInGB = 0
    $currentStandardUnlockedStorageUsageInGB = 0
    $currentPremiumUnlockedStorageUsageInGB = 0

    $currentRegionSizes = Get-AzVMSize -Location $region -ErrorAction SilentlyContinue
    Write-LogInfo "Get-AzVMSize -Location $region"
    $currentRegionUsage = Get-AzVMUsage -Location $region -ErrorAction SilentlyContinue
    Write-LogInfo "Get-AzVMUsage -Location $region"
    $currentRegionAllowedCores = ($currentRegionUsage | Where-Object { $_.Name.Value -eq "cores" }).Limit
    if (-not $currentRegionAllowedCores) {
        $currentRegionAllowedCores = 0
    }

    $regionCounter += 1
    Write-LogInfo "[$regionCounter/$($allRegions.Count)]. $($region)"

    foreach ($resource in $allResources) {
        if ($resource.Location -eq $region -and $resource.ResourceType -eq $VM_String) {
            $currentVMs += 1
            Write-LogInfo "+1 : $($resource.ResourceType) : $($resource.Name)"
            $currentVMStatus = $allVMStatus | Where-Object { $_.ResourceGroupName -eq $resource.ResourceGroupName -and $_.Name -eq $resource.Name }
            $currentUsedCores += ($currentRegionSizes | Where-Object { $_.Name -eq $($currentVMStatus.HardwareProfile.VmSize) }).NumberOfCores
            if ($($currentVMStatus.PowerState) -imatch "VM deallocated") {
                $currentDeallocatedCores += ($currentRegionSizes | Where-Object { $_.Name -eq $($currentVMStatus.HardwareProfile.VmSize) }).NumberOfCores
            }
        }
        if ($resource.Location -eq $region -and $resource.ResourceType -eq $storage_String) {
            Write-LogInfo "+1 : $($resource.ResourceType) : $($resource.Name)"
            $currentStorageAccounts += 1
            $StorageAccountObject = $allStorageAccounts | Where-Object { $_.StorageAccountName -eq $resource.Name }
            $DataUsage = Get-StorageAccountUsage -storageAccountObject $StorageAccountObject
            $currentStandardLockedStorageUsageInGB += $DataUsage[0]
            $currentPremiumLockedStorageUsageInGB += $DataUsage[1]
            $currentStandardUnlockedStorageUsageInGB += $DataUsage[2]
            $currentPremiumUnlockedStorageUsageInGB += $DataUsage[3]
        }
        if ($resource.Location -eq $region -and $resource.ResourceType -eq $ManagedDisk_String) {
            Write-LogInfo "+1 : $($resource.ResourceType) : $($resource.Name)"
            $ManagedDisks = $allManagedDisks | Where-Object { $_.Name -eq $resource.Name }
            foreach ($ManagedDiskObject in $ManagedDisks) {
                $DataUsage = Get-ManagedDiskUsage -ManagedDiskObject $ManagedDiskObject
                $currentStandardLockedStorageUsageInGB += $DataUsage[0]
                $currentPremiumLockedStorageUsageInGB += $DataUsage[1]
                $currentStandardUnlockedStorageUsageInGB += $DataUsage[2]
                $currentPremiumUnlockedStorageUsageInGB += $DataUsage[3]
            }
        }
        if ($resource.Location -eq $region -and $resource.ResourceType -eq $VNET_String) {
            Write-LogInfo "+1 : $($resource.ResourceType) : $($resource.Name)"
            $currentVNETs += 1
        }
        if ($resource.Location -eq $region -and $resource.ResourceType -eq $PublicIP_String) {
            Write-LogInfo "+1 : $($resource.ResourceType) : $($resource.Name)"
            $currentPublicIPs += 1
        }
    }
    if ($currentRegionAllowedCores -gt 0) {
        $RegionUsagePercent = $([math]::Round($currentUsedCores * 100 / $currentRegionAllowedCores, 1))
    } else {
        $RegionUsagePercent = 0
    }
    $CurrentTotalStorageUsage = $currentStandardLockedStorageUsageInGB + $currentPremiumLockedStorageUsageInGB `
        + $currentStandardUnlockedStorageUsageInGB + $currentPremiumUnLockedStorageUsageInGB
    Write-LogInfo "|--Current VMs: $currentVMs"
    Write-LogInfo "|--Current Storages: $currentStorageAccounts"
    Write-LogInfo "|--Current Locked Standard Storage (GB): $currentStandardLockedStorageUsageInGB"
    Write-LogInfo "|--Current Locked Premium Storage (GB): $currentPremiumLockedStorageUsageInGB"
    Write-LogInfo "|--Current Unlocked Standard Storage (GB): $currentStandardUnlockedStorageUsageInGB"
    Write-LogInfo "|--Current Unlocked Premium Storage (GB): $currentPremiumUnLockedStorageUsageInGB"
    Write-LogInfo "|--Current Total Storage (GB): $CurrentTotalStorageUsage"
    Write-LogInfo "|--Current VNETs: $currentVNETs"
    Write-LogInfo "|--Current PublicIPs: $currentPublicIPs"
    Write-LogInfo "|--Current Used Cores: $currentUsedCores"
    Write-LogInfo "|--Current Allowed Cores: $currentRegionAllowedCores"
    Write-LogInfo "|--Current Deallocated Cores: $currentDeallocatedCores"
    Write-LogInfo "------------------------------------------------------"
    $currentHTMLNode = $currentHTMLNode.Replace("Current_Serial", "$regionCounter")
    $currentHTMLNode = $currentHTMLNode.Replace("Current_Region", "$($region)")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_VMs", "$currentVMs")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_Used_Cores", "$currentUsedCores")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_Deallocated_Cores", "$currentDeallocatedCores")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_Allowed_Cores", "$currentRegionAllowedCores")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_Core_Percent", "$RegionUsagePercent")
    if ($RegionUsagePercent -gt 80) {
        $currentHTMLNode = $currentHTMLNode.Replace("CORE_CLASS", "tg-amwmred")
    } else {
        $currentHTMLNode = $currentHTMLNode.Replace("CORE_CLASS", "tg-amwmgreen")
    }
    $currentHTMLNode = $currentHTMLNode.Replace("Region_SA", "$currentStorageAccounts")
    $currentHTMLNode = $currentHTMLNode.Replace("Current_Overall_Storage_GB", "$CurrentTotalStorageUsage")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_PublicIP", "$currentPublicIPs")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_VNET", "$currentVNETs")
    #Add-Content -Path $FinalHtmlFile -Value $currentHTMLNode
    $UsageReport += $currentHTMLNode

    $totalVMs += $currentVMs
    $totalVNETs += $currentVNETs
    $totalPublicIPs += $currentPublicIPs
    $totalUsedCores += $currentUsedCores
    $totalAllowedCores += $currentRegionAllowedCores
    $totalDeallocatedCores += $currentDeallocatedCores
    $totalStorageAccounts += $currentStorageAccounts
    $totalStandardLockedStorageUsageInGB += $currentStandardLockedStorageUsageInGB
    $totalPremiumLockedStorageUsageInGB += $currentPremiumLockedStorageUsageInGB
    $totalStandardUnlockedStorageUsageInGB += $currentStandardUnlockedStorageUsageInGB
    $totalPremiumUnlockedStorageUsageInGB += $currentPremiumUnlockedStorageUsageInGB
    $totalOverallStorageUsageInGB += $CurrentTotalStorageUsage
    $SubscriptionID = $subscription.Id
    $SubscriptionName = $subscription.Name
    $currentRegion = $region
    $TimeStamp = "$($psttime.Year)-$($psttime.Month)-$($psttime.Day) $($psttime.Hour):$($psttime.Minute):$($psttime.Second)"
    if ($UploadToDB) {
        $SQLQuery += "('$SubscriptionID','$SubscriptionName','$currentRegion','$TimeStamp',$currentVMs,$currentUsedCores,$currentDeallocatedCores,$($currentUsedCores+$currentDeallocatedCores),$currentRegionAllowedCores,$RegionUsagePercent,$currentStandardLockedStorageUsageInGB,$currentStandardUnlockedStorageUsageInGB,$currentPremiumLockedStorageUsageInGB,$currentPremiumUnlockedStorageUsageInGB,$currentStorageAccounts,$currentPublicIPs,$currentVNETs),"
    }

}

$htmlSummary = $htmlFileSummary
$htmlSummary = $htmlSummary.Replace("Total_VMs", "$totalVMs")
$htmlSummary = $htmlSummary.Replace("Total_Used_Cores", "$totalUsedCores")
$htmlSummary = $htmlSummary.Replace("Total_Deallocated_Cores", "$totalDeallocatedCores")
$htmlSummary = $htmlSummary.Replace("Total_Allowed_Cores", "$totalAllowedCores")
$htmlSummary = $htmlSummary.Replace("Total_Core_Percent", "$RegionUsagePercent")
if ($RegionUsagePercent -gt 80) {
    $htmlSummary = $htmlSummary.Replace("CORE_CLASS", "tg-l2ozred")
} else {
    $htmlSummary = $htmlSummary.Replace("CORE_CLASS", "tg-l2ozgreen")
}
$htmlSummary = $htmlSummary.Replace("Total_SA", "$totalStorageAccounts")
$htmlSummary = $htmlSummary.Replace("Allowed_SA", "250")
$htmlSummary = $htmlSummary.Replace("Total_Overall_Storage_GB", "$totalOverallStorageUsageInGB")
$htmlSummary = $htmlSummary.Replace("Total_PublicIP", "$totalPublicIPs")
$htmlSummary = $htmlSummary.Replace("Total_VNET", "$totalVNETs")
$UsageReport = $UsageReport.Replace("FINAL_SUMMARY", $htmlSummary)
$UsageReport += '</table>'

#region Upload usage to DB
if ($UploadToDB) {
    $SQLQuery += "('$SubscriptionID','$SubscriptionName','Total','$TimeStamp',$totalVMs,$totalUsedCores,$totalDeallocatedCores,$($totalUsedCores+$totalDeallocatedCores),$totalAllowedCores,$RegionUsagePercent,$totalStandardLockedStorageUsageInGB,$totalStandardUnlockedStorageUsageInGB,$totalPremiumLockedStorageUsageInGB,$totalPremiumUnlockedStorageUsageInGB,$totalStorageAccounts,$totalPublicIPs,$totalVNETs)"
    try {
        Write-LogInfo $SQLQuery
        $connection = New-Object System.Data.SqlClient.SqlConnection
        $connection.ConnectionString = $connectionString
        $connection.Open()

        $command = $connection.CreateCommand()
        $command.CommandText = $SQLQuery
        $null = $command.executenonquery()
        $connection.Close()
        Write-LogInfo "Uploading data to DB done!!"
    } catch {
        Write-LogInfo $_.Exception | format-list -force
    }
}

#endregion

Write-LogInfo "Getting top 20 VMs."
.\Get-SubscriptionUsageTopVMs.ps1 -TopVMsCount 20 -SubscriptionId $subscription.SubscriptionId

$TopVMsHTMLReport = (Get-Content -Path .\vmAge.html)

$FinalEmailSummary += $htmlFileStart

foreach ($line in $TopVMsHTMLReport.Split("`n")) {
    $FinalEmailSummary += $line
}
foreach ($line in $UsageReport.Split("`n")) {
    # Removing the Resource Usage Table
    # $FinalEmailSummary += $line
}

$FinalEmailSummary += '<p style="text-align: right;"><em><span style="font-size: 18px;"><span style="font-family: times new roman,times,serif;"></span></span></em></p>'
#endregion

Add-Content -Path $FinalHtmlFile -Value $FinalEmailSummary -Verbose
Set-Content -Path $EmailSubjectTextFile -Value "Azure Subscription Daily Utilization Report: $($psttime.Year)/$($psttime.Month)/$($psttime.Day)"
Write-LogInfo "Usage summary is ready. Click Here to see - https://linuxpipeline.westus2.cloudapp.azure.com/view/Utilities/job/tool-monitor-subscription-usage/"
