# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation

# Description: This script lists the VMs in the current subscription and lists our Tags and VMAges.
param 
(
    [switch] $UseSecretsFile,
    [switch] $IncludeAge,
    $AzureSecretsFile,
    [string] $Region,
    [string] $VmSize,
    [string] $Tags
)

#Load libraries
Get-ChildItem ..\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

#When given -UseSecretsFile or an AzureSecretsFile path, we will attempt to search the path or the environment variable.
if( $UseSecretsFile -or $AzureSecretsFile )
{
    #Read secrets file and terminate if not present.
    if ($AzureSecretsFile)
    {
        $secretsFile = $AzureSecretsFile
    }
    elseif ($env:Azure_Secrets_File) 
    {
        $secretsFile = $env:Azure_Secrets_File
    }
    else 
    {
        LogMsg "-AzureSecretsFile and env:Azure_Secrets_File are empty. Exiting."
        exit 1
    }
    if ( Test-Path $secretsFile)
    {
        LogMsg "Secrets file found."
        .\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $secretsFile
        $xmlSecrets = [xml](Get-Content $secretsFile)
    }
    else
    {
        LogMsg "Secrets file not found. Exiting."
        exit 1
    }
}

function Get-VMAgeFromDisk()
{
    param
    (
        [Parameter(Mandatory=$true)] $vm
    )
    $storageKind = "none"
    $ageDays = -1
    if( $vm.StorageProfile.OsDisk.Vhd.Uri )
    {
        $vhd = $vm.StorageProfile.OsDisk.Vhd.Uri
        # The URI needs to be broken apart to find the storage account, the container, and the file.
        #       $storageAccount                                 $container  $blob
        #http://standardlrssomenumberhere.blob.core.windows.net/vhds        /nameOfDrive.vhd
        $storageAccount = $vhd.Split("/")[2].Split(".")[0]
        $container = $vhd.Split("/")[3]
        $blob = $vhd.Split("/")[4]
    
        $storageKind = "blob"
        $blobStorageUsed = Get-AzureRmStorageAccount | where {  $($_.StorageAccountName -eq $storageAccount) -and $($_.Location -eq $vm.Location) }
        if( $blobStorageUsed )
        {
            Set-AzureRmCurrentStorageAccount -ResourceGroupName $blobStorageUsed.ResourceGroupName -Name $storageAccount > $null
            $blobDetails = Get-AzureStorageBlob -Container $container -Blob $blob -ErrorAction SilentlyContinue
            if( $blobDetails )
            {
                $copyCompletion = $blobDetails.ICloudBlob.CopyState.CompletionTime
                $age = $($(get-Date)-$copyCompletion.DateTime)
                $ageDays = $age.Days
            }
        }
    }
    else
    {
        $storageKind = "disk"
        $osdisk = Get-AzureRmDisk -ResourceGroupName $vm.ResourceGroupName -DiskName $vm.StorageProfile.OsDisk.Name -ErrorAction SilentlyContinue
        if( $osdisk )
        {
            $age = $($(Get-Date) - $osDisk.TimeCreated)
            $ageDays = $($age.Days)
        }
    }
    $ageDays
}

#Get all VMs and enumerate thru them adding items to results list.
$allVMs = Get-AzureRmVM
$allRGs = Get-AzureRmResourceGroup

$results = @()


$usingRegion = $false
$usingVmSize = $false
$usingTags = $false

foreach ($vm in $allVMs) 
{
    $include = $false
    $hasFailed = $false

    #Check to see if the Region is being used.
    if( $Region -ne "" )
    {
        $usingRegion = $true
        if( $vm.Location -like $Region )
        {
            $include = $true
        }
        else {
            $include = $false
            $hasFailed = $true
        }
    }
    #Check to see if the VmSize is being used.
    if( $VmSize -ne "" -and $hasFailed -eq $false )
    {
        $usingVmSize = $true
        if( $vm.HardwareProfile.VmSize -like $VmSize )
        {
            $include = $true
        }
        else {
            $include = $false
            $hasFailed = $true
        }
    }
    #Check to see if the comma seperated values in Tags are like any tags on the ResourceGroup.
    if( $Tags -ne "" -and $hasFailed -eq $false )
    {
        $include = $false
        $usingTags = $true
        $eachTag = $Tags -Split ","
        $rg = $allRGs | Where ResourceGroupName -eq $vm.ResourceGroupName
        foreach( $tag in $eachTag )
        {
            if( $rg.Tags.BuildUrl -like $tag )
            {
                $include = $true
            }
            if( $rg.Tags.BuildUser -like $tag )
            {
                $include = $true
            }
            if( $rg.Tags.BuildMachine -like $tag )
            {
                $include = $true
            }
            if( $rg.Tags.TestName -like $tag )
            {
                $include = $true
            }
        }
        if( $include -eq $false )
        {
            $hasFailed = $true
        }
    }

    if( $hasFailed -eq $false )
    {
        #Check for NO filters.
        if( $usingRegion -eq $usingVmSize -and $usingVmSize -eq $usingTags -and $usingVmSize -eq $false )
        {
            $include = $true
        }
    }

    if( $include -eq $true ) 
    {
        $result = @{
            'VMName' = $vm.Name
            'VMSize' = $vm.HardwareProfile.VmSize
            'VMRegion' = $vm.Location
            'ResourceGroupName' = $vm.ResourceGroupName
            'vm' = $vmIndex
        }
        $results += $result
    }
}
$results = $results | Foreach-Object { [pscustomobject] $_ }
#Now add the resource group details.
foreach( $result in $results )
{
    $rg = $allRGs | Where ResourceGroupName -eq $result.ResourceGroupName
    $result | Add-Member BuildURL $rg.Tags.BuildURL
    $result | Add-Member BuildUser $rg.Tags.BuildUser
    $result | Add-Member TestName $rg.Tags.TestName
    $result | Add-Member CreationDate $rg.Tags.CreationDate

    if( $rg.Tags.CreationDate )
    { 
        $days = ([DateTime]::Now - $rg.Tags.CreationDate).Days
        $result | Add-Member RGAge $days
    }
    else {
        $result | Add-Member RGAge ""
    }
}

#Perform costly age check
if( $IncludeAge )
{
    $ageIndex = 0
    LogMsg "Collecting VM age from disk details for $($results.Length) machines."
    foreach( $result in $results )
    {
        $result | Add-Member VMAge (Get-VMAgeFromDisk $allVms[$result.vm])
        $ageIndex = $ageIndex + 1
    }
}
#trim out the vm index.
foreach( $result in $results )
{
    $result.PSObject.Properties.Remove('vm')
}
#output the table
$results | Format-Table 