# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation

# Description: This script reads the ages of all the VMs in a subscription and stores the top N entries in .\vmAge.html


param
(
    [int]$TopVMsCount=20,
    [string] $LogFileName = "GetSubscriptionUsageTopVMs.log"
)
if (!$global:LogFileName){
  Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
}
Get-ChildItem ..\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }
#region HTML File structure
$htmlHeader = '
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
<table class="tm">
  <tr>
    <th class="tm-dk6e" colspan="9">Top 20 VMs by their Weight (Age*CoreCount)</th>
  </tr>
  <tr>
    <td class="tm-7k3a">Sr</td>
    <td class="tm-7k3a">Weight</td>
    <td class="tm-7k3a">VMName</td>
    <td class="tm-7k3a">ResourceGroup</td>
    <td class="tm-7k3a">Location</td>
    <td class="tm-7k3a">Size</td>
    <td class="tm-7k3a">VM Age</td>
    <td class="tm-7k3a">Core Count</td>
  </tr>
'

#$htmlNodeGreen =
#'
#  <tr>
#    <td class="tm-yw4l">SR_ID</td>
#    <td class="tm-yw4l">VM_WEIGHT</td>
#    <td class="tm-ys9u">OFF</td>
#    <td class="tm-yw4l">INSTANCE_NAME</td>
#    <td class="tm-yw4l">RESOURCE_GROUP_NAME</td>
#    <td class="tm-yw4l">VM_REGION</td>
#    <td class="tm-yw4l">VM_SIZE</td>
#    <td class="tm-yw4l">VM_AGE</td>
#    <td class="tm-yw4l">VM_CORE</td>
#  </tr>
#'

$htmlNodeRed =
'
  <tr>
    <td class="tm-yw4l">SR_ID</td>
    <td class="tm-yw4l">VM_WEIGHT</td>
    <td class="tm-yw4l">INSTANCE_NAME</td>
    <td class="tm-yw4l">RESOURCE_GROUP_NAME</td>
    <td class="tm-yw4l">VM_REGION</td>
    <td class="tm-yw4l">VM_SIZE</td>
    <td class="tm-yw4l">VM_AGE</td>
    <td class="tm-yw4l">VM_CORE</td>
  </tr>
'

$htmlEnd =
'
</table>
'
#endregion
$tick = (Get-Date).Ticks
$VMAgeHTMLFile = "vmAge.html"
$cacheFilePath = "cache.results-$tick.json"

#region Get VM Age
$then = Get-Date
Write-LogInfo "Elapsed Time: $($(Get-Date) - $then)"
$allSizes = @{}
Write-LogInfo "Running: Get-AzLocation..."
$allRegions = (Get-AzLocation | Where-Object { $_.Providers -imatch "Microsoft.Compute" }).Location | Sort-Object
foreach( $region in $allRegions )
{
    Write-LogInfo "Running:  Get-AzVMSize -Location $($region)"
    $allSizes[ $region ] = Get-AzVMSize -Location $region
}
try
{
	Write-LogInfo "Running: Get-AzVM -Status"
	$allVMStatus = Get-AzVM -Status
	Write-LogInfo "Running: Get-AzStorageAccount"
	$sas = Get-AzStorageAccount
}
catch {
    Write-LogInfo "Error while fetching data. Please try again."
    Set-Content -Path $VMAgeHTMLFile -Value "There was some error in fetching data from Azure today."
    exit 1
}


Write-LogInfo "Elapsed Time: $($(Get-Date) - $then)"
$finalResults = @()
foreach( $vm in $allVMStatus )
{
  $deallocated = $false
  if( $vm.PowerState -imatch "VM deallocated" )
  {
        $PowerStatusString = " [OFF] "
        $deallocated = $true
  }
  else
  {
        $PowerStatusString = " [ON] "
  }
  Write-LogInfo "[$($(Get-Date) - $then)] $PowerStatusString -Name $($vm.Name) -ResourceGroup $($vm.ResourceGroupName) Size=$($vm.HardwareProfile.VmSize)"
  $storageKind = "None"
  $ageDays = -1
  $idleDays = -1

  if( $vm.StorageProfile.OsDisk.Vhd.Uri )
  {
    $vhd = $vm.StorageProfile.OsDisk.Vhd.Uri
    $storageAccount = $vhd.Split("/")[2].Split(".")[0]
    $container = $vhd.Split("/")[3]
    $blob = $vhd.Split("/")[4]

    $storageKind = "blob"

    $foo = $sas | Where-Object {  $($_.StorageAccountName -eq $storageAccount) -and $($_.Location -eq $vm.Location) }
    Set-AzCurrentStorageAccount -ResourceGroupName $foo.ResourceGroupName -Name $storageAccount > $null
    $blobDetails = Get-AzStorageBlob -Container $container -Blob $blob
    $copyCompletion = $blobDetails.ICloudBlob.CopyState.CompletionTime
    $lastWriteTime = $blobDetails.LastModified
    $age = $($(Get-Date)-$copyCompletion.DateTime)
    $idle = $($(Get-Date)-$lastWriteTime.DateTime)
    $ageDays = $age.Days
    $idleDays = $idle.Days

    Write-LogInfo " Age = $ageDays  Idle = $idleDays"
  }
  else
  {
    $storageKind = "disk"
	Write-LogInfo "Running:  Get-AzDisk -ResourceGroupName $($vm.ResourceGroupName) -DiskName $($vm.StorageProfile.OsDisk.Name)"
    $osdisk = Get-AzDisk -ResourceGroupName $vm.ResourceGroupName -DiskName $vm.StorageProfile.OsDisk.Name
    if( $osdisk.TimeCreated )
    {
      $age = $($(Get-Date) - $osDisk.TimeCreated)
      $ageDays = $($age.Days)
      Write-LogInfo " Age = $($age.Days)"
    }
  }
  $coreCount = $allSizes[ $vm.Location ] | Where-Object { $_.Name -eq $($vm.HardwareProfile.VmSize) }
  $newEntry = @{
    Name=$vm.Name
    resourceGroup=$vm.ResourceGroupName
    location=$vm.Location
    coreCount=$coreCount.NumberOfCores
    vmSize=$($vm.HardwareProfile.VmSize)
    Age=$ageDays
    Idle=$idleDays
    Weight=$($coreCount.NumberOfCores * $ageDays)
    StorageKind=$storageKind
    Deallocated=$deallocated
  }

  $finalResults += $newEntry
}
Write-LogInfo "FinalResults.Count = $($finalResults.Count)"
$finalResults | ConvertTo-Json -Depth 10 | Set-Content "$cacheFilePath"
#endregion

#region Build HTML Page

$VMAges = ConvertFrom-Json -InputObject  ([string](Get-Content -Path "$cacheFilePath"))
$VMAges   = $VMAges | Sort-Object -Descending Weight
$finalHTMLString = $htmlHeader

$RGLinkHtml = '<a href="https://ms.portal.azure.com/#resource/subscriptions/' + "$subscriptionID" + '/resourceGroups/RESOURCE_GROUP_NAME/overview" target="_blank" rel="noopener">RESOURCE_GROUP_NAME</a>'
$VMLinkHtml = '<a href="https://ms.portal.azure.com/#resource/subscriptions/' + "$subscriptionID" + '/resourceGroups/RESOURCE_GROUP_NAME/providers/Microsoft.Compute/virtualMachines/INSTANCE_NAME/overview" target="_blank" rel="noopener">INSTANCE_NAME</a>'

$maxCount = $TopVMsCount
$i = 0
foreach ($currentVMNode in $VMAges)
{
    if ( $currentVMNode -ne $null)
    {
        if ( $currentVMNode.Deallocated -eq $true)
        {
			#Don't consider deallocated VMs in this count.
            #$currentVMHTMLNode = $htmlNodeGreen
        }
        else
        {
            $i += 1
            $currentVMHTMLNode = $htmlNodeRed
            $currentVMHTMLNode = $currentVMHTMLNode.Replace("SR_ID","$i")
            $currentVMHTMLNode = $currentVMHTMLNode.Replace("VM_WEIGHT","$($currentVMNode.Weight)")
            #$currentVMHTMLNode = $currentVMHTMLNode.Replace("INSTANCE_NAME","$($currentVMNode.Name)")
            #$currentVMHTMLNode = $currentVMHTMLNode.Replace("RESOURCE_GROUP_NAME","$($currentVMNode.resourceGroup)")
            $currentVMHTMLLink = $VMLinkHtml.Replace("RESOURCE_GROUP_NAME","$($currentVMNode.resourceGroup)").Replace("INSTANCE_NAME","$($currentVMNode.Name)")
            $currentRGHTMLLink = $RGLinkHtml.Replace("RESOURCE_GROUP_NAME","$($currentVMNode.resourceGroup)")
            $currentVMHTMLNode = $currentVMHTMLNode.Replace("INSTANCE_NAME","$currentVMHTMLLink")
            $currentVMHTMLNode = $currentVMHTMLNode.Replace("RESOURCE_GROUP_NAME","$currentRGHTMLLink")
            $currentVMHTMLNode = $currentVMHTMLNode.Replace("VM_REGION","$($currentVMNode.location)")
            $currentVMHTMLNode = $currentVMHTMLNode.Replace("VM_SIZE","$($currentVMNode.vmSize)")
            $currentVMHTMLNode = $currentVMHTMLNode.Replace("VM_AGE","$($currentVMNode.Age)")
            $currentVMHTMLNode = $currentVMHTMLNode.Replace("VM_CORE","$($currentVMNode.coreCount)")
            $finalHTMLString += $currentVMHTMLNode
            if ( $i -ge $maxCount)
            {
              break
            }
        }
    }
}

$finalHTMLString += $htmlEnd

Set-Content -Value $finalHTMLString -Path $VMAgeHTMLFile
#endregion

#region Original HTML Table structure
<#
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
<table class="tm">
  <tr>
    <th class="tm-dk6e" colspan="9">Top 100 VMs by their Weigh (Age*CoreCount)</th>
  </tr>
  <tr>
    <td class="tm-7k3a">Sr</td>
    <td class="tm-7k3a">Weight</td>
    <td class="tm-7k3a">PowerStatus</td>
    <td class="tm-7k3a">VMName</td>
    <td class="tm-7k3a">ResourceGroup</td>
    <td class="tm-7k3a">Location</td>
    <td class="tm-7k3a">Size</td>
    <td class="tm-7k3a">VM Age</td>
    <td class="tm-7k3a">Core Count</td>
  </tr>
  <tr>
    <td class="tm-yw4l">1</td>
    <td class="tm-yw4l">VM_WEIGHT</td>
    <td class="tm-ys9u">POWER_STATUS_GREEN</td>
    <td class="tm-yw4l">INSTANCE_NAME</td>
    <td class="tm-yw4l">RESOURCE_GROUP_NAME</td>
    <td class="tm-yw4l">VM_REGION</td>
    <td class="tm-yw4l">VM_SIZE</td>
    <td class="tm-yw4l">VM_AGE</td>
    <td class="tm-yw4l">VM_CORE</td>
  </tr>
  <tr>
    <td class="tm-6k2t">2</td>
    <td class="tm-6k2t">VM_WEIGHT</td>
    <td class="tm-xa7z">POWER_STATUS_RED</td>
    <td class="tm-6k2t">INSTANCE_NAME</td>
    <td class="tm-6k2t">RESOURCE_GROUP_NAME</td>
    <td class="tm-6k2t">VM_REGION</td>
    <td class="tm-6k2t">VM_SIZE</td>
    <td class="tm-6k2t">VM_AGE</td>
    <td class="tm-6k2t">VM_CORE</td>
  </tr>
</table>
#>
#endregion
