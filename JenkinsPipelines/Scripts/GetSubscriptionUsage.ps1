##############################################################################################
# GetSibscriptionUsgae.ps1
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

param 
( 
    [switch] $UploadToDB,
    $customSecretsFilePath=""
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

if ($customSecretsFilePath)
{
    $secretsFile = $customSecretsFilePath
}
elseif ($env:Azure_Secrets_File) 
{
    $secretsFile = $env:Azure_Secrets_File
}
else 
{
    LogMsg "-customSecretsFilePath and env:Azure_Secrets_File are empty. Exiting."
    exit 1
}
if ( Test-Path $secretsFile)
{
	LogMsg "AzureSecrets.xml found."
	.\Utilities\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $secretsFile
	$xmlSecrets = [xml](Get-Content $secretsFile)
}
else
{
	LogMsg "$secretsFile not found. Exiting."
	exit 1
}

try 
{
    $EmailSubjectTextFile =  ".\ShowSubscriptionUsageEmailSubject.txt"
    $FinalHtmlFile = ".\SubscriptionUsage.html"
    $pstzone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Pacific Standard Time")
    $psttime = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(),$pstzone)
    
    $subscription = Get-AzureRmSubscription
    LogMsg "Running: Get-AzureRmResource..."
    $allResources = Get-AzureRmResource
    LogMsg "Running: Get-AzureRmVM -Status..."
    $allVMStatus = Get-AzureRmVM -Status
    LogMsg "Running: Get-AzureRmLocation..."
    $allRegions = (Get-AzureRmLocation | Where-Object { $_.Providers -imatch "Microsoft.Compute" }).Location | Sort-Object
}
catch 
{
    LogMsg "Error while fetching data. Please try again."
    Set-Content -Path $FinalHtmlFile -Value "There was some error in fetching data from Azure today."
    Set-Content -Path $EmailSubjectTextFile -Value "Azure Subscription Daily Utilization Report: $($psttime.Year)/$($psttime.Month)/$($psttime.Day)"
    exit 1
}

#region HTML file header
$htmlFileStart = '
<style type="text/css">
.tg  {border-collapse:collapse;border-spacing:0;border-color:#999;}
.tg td{font-family:Arial, sans-serif;font-size:14px;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#444;background-color:#F7FDFA;}
.tg th{font-family:Arial, sans-serif;font-size:14px;font-weight:normal;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#fff;background-color:#26ADE4;}
.tg .tg-baqh{text-align:left;vertical-align:top}
.tg .tg-lqy6{text-align:right;vertical-align:top}
.tg .tg-lqy6bold{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-yw4l{vertical-align:top}
.tg .tg-amwm{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-amwmleft{text-align:left;font-weight:bold;vertical-align:top}
.tg .tg-amwmred{color:#fe0000;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-amwmgreen{color:#036400;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-9hbo{font-weight:bold;vertical-align:top}
.tg .tg-l2oz{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-l2ozred{color:#fe0000;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-l2ozgreen{color:#036400;font-weight:bold;text-align:right;vertical-align:top}
</style>

<p style="text-align: left;"><em>Last refreshed&nbsp;<strong>DATE_TIME. </strong></em> <a href="https://msit.powerbi.com/groups/a765920a-87fb-4668-bf25-780ff25639be/reports/9e04d866-5c5b-4020-aa63-f61d952c5b75/ReportSection" target="_blank" rel="noopener"><em><strong>Click Here</strong></em></a> to see the report in PowerBI.</p>

<table class="tg">
  <tr>
    <th class="tg-amwmleft">SR. #</th>
    <th class="tg-amwmleft">Region</th>
    <th class="tg-amwm">Total VMs</th>
    <th class="tg-amwm">vCPU Cores (Used / Deallocated / Max Allowed)</th>
    <th class="tg-amwm">vCPU Core usage %</th>
    <th class="tg-amwm">Storage Accounts</th>
    <th class="tg-amwm">Public IPs</th>
    <th class="tg-amwm">Virtual Networks</th>
  </tr>
  '
  
$htmlFileStart = $htmlFileStart.Replace("DATE_TIME","$($psttime.DateTime) PST")
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
    <td class="tg-l2oz">Total_PublicIP</td>
    <td class="tg-l2oz">Total_VNET</td>
  </tr>
'
#endregion

$storage_String = "Microsoft.Storage/storageAccounts"
$VM_String = "Microsoft.Compute/virtualMachines"
$VNET_String = "Microsoft.Network/virtualNetworks"
$PublicIP_String = "Microsoft.Network/publicIPAddresses"

$regionCounter = 0
$totalVMs = 0
$totalVNETs = 0
$totalPublicIPs = 0
$totalUsedCores = 0
$totalAllowedCores = 0
$totalDeallocatedCores = 0
$totalStorageAccounts = 0

#region Create HTML report

$FinalEmailSummary = ""
$FinalEmailSummary += $htmlFileStart

$FinalEmailSummary += "FINAL_SUMMARY"

if ($UploadToDB)
{
    $dataSource = $xmlSecrets.secrets.DatabaseServer
    $user = $xmlSecrets.secrets.DatabaseUser
    $password = $xmlSecrets.secrets.DatabasePassword
    $database = $xmlSecrets.secrets.DatabaseName
    $dataTableName = "SubscriptionUsage"
    $connectionString = "Server=$dataSource;uid=$user; pwd=$password;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    $SQLQuery = "INSERT INTO $dataTableName (SubscriptionID,SubscriptionName,Region,DateAndTime,TotalVMs,vCPUAllocated,vCPUDeAllocated,vCPUTotal,vCPUMaxAllowed,vCPUPercentUsed,PremiumStorages,StanardStorages,TotalStorages,PublicIPs,VirtualNetworks) VALUES "
}
foreach ($region in $allRegions)
{
 
    $currentHTMLNode = $htmlFileRow
    $currentVMs = 0
    $currentVNETs = 0
    $currentPublicIPs = 0
    $currentUsedCores = 0
    $currentAllowedCores = 0
    $currentDeallocatedCores = 0
    $currentStorageAccounts = 0
    $currentRegionSizes = Get-AzureRmVMSize -Location $region
    LogMsg "Get-AzureRmVMSize -Location $region"
    $currentRegionUsage =  Get-AzureRmVMUsage -Location $region
    LogMsg "Get-AzureRmVMUsage -Location $region"
    $currentRegionAllowedCores = ($currentRegionUsage | Where-Object { $_.Name.Value -eq "cores"}).Limit 
    
    $regionCounter+= 1
    LogMsg "[$regionCounter/$($allRegions.Count)]. $($region)"

    foreach ($resource in $allResources)
    {
        if ( $resource.Location -eq $region -and $resource.ResourceType -eq $VM_String)
        {
            $currentVMs += 1
            LogMsg "+1 : $($resource.ResourceType) : $($resource.Name)"
            $currentVMStatus = $allVMStatus | Where-Object { $_.ResourceGroupName -eq $resource.ResourceGroupName -and $_.Name -eq $resource.Name }            
            $currentUsedCores += ($currentRegionSizes | Where-Object { $_.Name -eq $($currentVMStatus.HardwareProfile.VmSize)}).NumberOfCores
            if ( $($currentVMStatus.PowerState) -imatch "VM deallocated")
            {
                $currentDeallocatedCores += ($currentRegionSizes | Where-Object { $_.Name -eq $($currentVMStatus.HardwareProfile.VmSize)}).NumberOfCores
            }
        }
        if ( $resource.Location -eq $region -and $resource.ResourceType -eq $storage_String)
        {
            LogMsg "+1 : $($resource.ResourceType) : $($resource.Name)"
            $currentStorageAccounts += 1
        }
        if ( $resource.Location -eq $region -and $resource.ResourceType -eq $VNET_String)
        {
            LogMsg "+1 : $($resource.ResourceType) : $($resource.Name)"
            $currentVNETs += 1
        }
        if ( $resource.Location -eq $region -and $resource.ResourceType -eq $PublicIP_String)
        {
            LogMsg "+1 : $($resource.ResourceType) : $($resource.Name)"
            $currentPublicIPs += 1
        }
    }
    LogMsg "|--Current VMs: $currentVMs"
    LogMsg "|--Current Storages: $currentStorageAccounts"
    LogMsg "|--Current VNETs: $currentVNETs"
    LogMsg "|--Current PublicIPs: $currentPublicIPs"
    LogMsg "|--Current Used Cores: $currentUsedCores"
    LogMsg "|--Current Allowed Cores: $currentRegionAllowedCores"
    LogMsg "|--Current Deallocated Cores: $currentDeallocatedCores"
    LogMsg "------------------------------------------------------"
    $currentHTMLNode = $currentHTMLNode.Replace("Current_Serial","$regionCounter")
    $currentHTMLNode = $currentHTMLNode.Replace("Current_Region","$($region)")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_VMs","$currentVMs")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_Used_Cores","$currentUsedCores")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_Deallocated_Cores","$currentDeallocatedCores")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_Allowed_Cores","$currentRegionAllowedCores")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_Core_Percent","$([math]::Round($currentUsedCores*100/$currentRegionAllowedCores,1))")
    if ( [math]::Round($currentUsedCores*100/$currentRegionAllowedCores,1) -gt 80 )
    {
        $currentHTMLNode = $currentHTMLNode.Replace("CORE_CLASS","tg-amwmred")
    }
    else
    {
        $currentHTMLNode = $currentHTMLNode.Replace("CORE_CLASS","tg-amwmgreen")
    }
    $currentHTMLNode = $currentHTMLNode.Replace("Region_SA","$currentStorageAccounts")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_PublicIP","$currentPublicIPs")
    $currentHTMLNode = $currentHTMLNode.Replace("Region_VNET","$currentVNETs")
    #Add-Content -Path $FinalHtmlFile -Value $currentHTMLNode
    $FinalEmailSummary += $currentHTMLNode
    
    $totalVMs += $currentVMs
    $totalVNETs += $currentVNETs
    $totalPublicIPs += $currentPublicIPs
    $totalUsedCores += $currentUsedCores
    $totalAllowedCores += $currentRegionAllowedCores
    $totalDeallocatedCores += $currentDeallocatedCores
    $totalStorageAccounts += $currentStorageAccounts
    $SubscriptionID = $subscription.Id
    $SubscriptionName = $subscription.Name
    $currentRegion = $region 
    $PremiumStorages = "NULL"
    $StanardStorages = "NULL"
    $TimeStamp = "$($psttime.Year)-$($psttime.Month)-$($psttime.Day) $($psttime.Hour):$($psttime.Minute):$($psttime.Second)"
    if ($UploadToDB)
    {
        $SQLQuery += "('$SubscriptionID','$SubscriptionName','$currentRegion','$TimeStamp',$currentVMs,$currentUsedCores,$currentDeallocatedCores,$($currentUsedCores+$currentDeallocatedCores),$currentRegionAllowedCores,$([math]::Round($currentUsedCores*100/$currentRegionAllowedCores,1)),$PremiumStorages,$StanardStorages,$currentStorageAccounts,$currentPublicIPs,$currentVNETs),"
    }

}

$htmlSummary = $htmlFileSummary
$htmlSummary = $htmlSummary.Replace("Total_VMs","$totalVMs")
$htmlSummary = $htmlSummary.Replace("Total_Used_Cores","$totalUsedCores")
$htmlSummary = $htmlSummary.Replace("Total_Deallocated_Cores","$totalDeallocatedCores")
$htmlSummary = $htmlSummary.Replace("Total_Allowed_Cores","$totalAllowedCores")
$htmlSummary = $htmlSummary.Replace("Total_Core_Percent","$([math]::Round($totalUsedCores*100/$totalAllowedCores,1))")
if ( $([math]::Round($totalUsedCores*100/$totalAllowedCores,1)) -gt 80 )
{
    $htmlSummary = $htmlSummary.Replace("CORE_CLASS","tg-l2ozred")
}
else
{
    $htmlSummary = $htmlSummary.Replace("CORE_CLASS","tg-l2ozgreen")
}
$htmlSummary = $htmlSummary.Replace("Total_SA","$totalStorageAccounts")
$htmlSummary = $htmlSummary.Replace("Allowed_SA","200")
$htmlSummary = $htmlSummary.Replace("Total_PublicIP","$totalPublicIPs")
$htmlSummary = $htmlSummary.Replace("Total_VNET","$totalVNETs")
$FinalEmailSummary = $FinalEmailSummary.Replace("FINAL_SUMMARY",$htmlSummary)
$FinalEmailSummary += '</table>'

#region Upload usage to DB
if ($UploadToDB)
{
    $SQLQuery += "('$SubscriptionID','$SubscriptionName','Total','$TimeStamp',$totalVMs,$totalUsedCores,$totalDeallocatedCores,$($totalUsedCores+$totalDeallocatedCores),$totalAllowedCores,$([math]::Round($totalUsedCores*100/$totalAllowedCores,1)),$PremiumStorages,$StanardStorages,$totalStorageAccounts,$totalPublicIPs,$totalVNETs)"
    try
    {
        LogMsg $SQLQuery
        $connection = New-Object System.Data.SqlClient.SqlConnection
        $connection.ConnectionString = $connectionString
        $connection.Open()

        $command = $connection.CreateCommand()
        $command.CommandText = $SQLQuery
        $result = $command.executenonquery()
        $connection.Close()
        LogMsg "Uploading data to DB done!!"
    }
    catch
    {
        LogMsg $_.Exception | format-list -force
    }
}

#endregion

LogMsg "Getting top 20 VMs."
.\JenkinsPipelines\Scripts\SubscriptionUsageTopVMs.ps1 -TopVMsCount 20

$TopVMsHTMLReport = (Get-Content -Path .\vmAge.html)

foreach ( $line in $TopVMsHTMLReport.Split("`n"))
{
    $FinalEmailSummary += $line
}

$FinalEmailSummary += '<p style="text-align: right;"><em><span style="font-size: 18px;"><span style="font-family: times new roman,times,serif;">&gt;</span></span></em></p>'
#endregion

Set-Content -Path $FinalHtmlFile -Value $FinalEmailSummary
Set-Content -Path $EmailSubjectTextFile -Value "Azure Subscription Daily Utilization Report: $($psttime.Year)/$($psttime.Month)/$($psttime.Day)"
LogMsg "Usage summary is ready. Click Here to see - https://linuxpipeline.westus2.cloudapp.azure.com/view/Utilities/job/tool-monitor-subscription-usage/"