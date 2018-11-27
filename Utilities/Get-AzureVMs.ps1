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
Get-ChildItem ..\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }
#When given -UseSecretsFile or an AzureSecretsFile path, we will attempt to search the path or the environment variable.
if( $UseSecretsFile -or $AzureSecretsFile )
{
    Write-LogInfo "Evaluating Secrets File"
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
        Write-LogInfo "-AzureSecretsFile and env:Azure_Secrets_File are empty. Exiting."
        exit 1
    }
    if ( Test-Path $secretsFile)
    {
        Write-LogInfo "Secrets file found."
        .\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $secretsFile
    }
    else
    {
        Write-LogInfo "Secrets file not found. Exiting."
        exit 1
    }
}

# Determine the age by finding the creation time for the osdrive of the VM.
function Get-VMAgeFromDisk()
{
    param
    (
        [Parameter(Mandatory=$true)] $vm
    )
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

        $blobStorageUsed = Get-AzureRmStorageAccount | where {  $($_.StorageAccountName -eq $storageAccount) -and $($_.Location -eq $vm.Location) }
        if( $blobStorageUsed )
        {
            Set-AzureRmCurrentStorageAccount -ResourceGroupName $blobStorageUsed.ResourceGroupName -Name $storageAccount > $null
            $blobDetails = Get-AzureStorageBlob -Container $container -Blob $blob -ErrorAction SilentlyContinue
            if( $blobDetails )
            {
                $copyCompletion = $blobDetails.ICloudBlob.CopyState.CompletionTime
                $age = $($(Get-Date)-$copyCompletion.DateTime)
                $ageDays = $age.Days
            }
        }
    }
    else
    {
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
foreach ($vm in $allVMs)
{
    $rg = $allRGs | Where-Object ResourceGroupName -eq $vm.ResourceGroupName

    $result = New-Object psobject
    $result | Add-Member VMName $($vm.Name)
    $result | Add-Member Size $($vm.HardwareProfile.VmSize)
    $result | Add-Member Region $($vm.Location)
    $result | Add-Member ResourceGroupName $($rg.ResourceGroupName)

    #Timestamp Date
    $PotentialDate = (($result.ResourceGroupName).Split("-") | Select-Object -Last 1) + '000000'
    $PossibleDate = $( $PotentialDate -match "^\d" -and $PotentialDate.Length -eq 18 )
    if( $PossibleDate -eq $true )
    {
        $when = $([datetime]([long]$PotentialDate))
        $ageInDays = ([datetime]::Now - $when).Days
        $result | Add-Member Age $ageInDays
    }
    #Get Tags (And Tag date if Timestamp wasn't there.)
    if( $rg.Tags )
    {
        if( $rg.Tags.BuildURL )
        {
            $result | Add-Member BuildURL $rg.Tags.BuildURL
        }
        if( $rg.Tags.TestName )
        {
            $result | Add-Member TestName $rg.Tags.TestName
        }
        if( $rg.Tags.BuildUser )
        {
            $result | Add-Member BuildUser $rg.Tags.BuildUser
        }
        if( $rg.Tags.BuildMachine )
        {
            $result | Add-Member BuildMachine $rg.Tags.BuildMachine
        }
        if( $rg.Tags.CreationTime )
        {
            $result | Add-Member CreationTime $rg.Tags.CreationTime
            #Update the age if we haven't already collected it.
            #This script is unlikely to execute unless we stop using a timestamp in our resource names.
            if( $null -ieq $result.Age )
            {
                $ageInDays = ([datetime]::Now - $rg.Tags.CreationTime).Days
                $result | Add-Member Age $ageInDays
            }
        }
    }
    #Check to see if the VM itself has it's own CreationTime tag.  If so, use that.
    #CreationTime tags can be added to individual VMs using Az CLI
    #   Example: az vm update --resource-group $rgName --name $vmName --set tags.CreationTime='08/08/2018 17:04:53'
    if( !($null -ieq $vm.Tags.CreationTime) )
    {
        if( $result.Age )
        {
            $result.PSObject.Properties.Remove( 'Age' )
        }
        $vmCreate = [datetime]"$($vm.Tags.CreationTime)"
        $ageInDays = ([datetime]::Now - $vmCreate).Days
        $result | Add-Member Age $ageInDays
    }

    #Finally compute the long time running age for remaining machines by looking at the disk details.
    if( $null -ieq $result.Age )  # Tag not present.
    {
        #This is a time-consuming process and shouldn't be used without intent.
        if( $IncludeAge )
        {
            $result | Add-Member vm $vm
        }
        $result | Add-Member Age "Undefined"
    }
    $results += $result
}

#Apply the filters.
# Region AND Size AND Tags
# Since we have already accumulated ALL the items, let's walk thru the selected filters
# and remove entries that do not match.
if( $Region )
{
    $filteredResults = @()
    foreach( $result in $results )
    {
        if( $result.Region -like $Region )
        {
            $filteredResults += $result
        }
    }
    $results = $filteredResults
}
if( $VmSize )
{
    $filteredResults = @()
    foreach( $result in $results )
    {
        if( $result.Size -like $VmSize )
        {
            $filteredResults += $result
        }
    }
    $results = $filteredResults
}
if( $Tags )
{
    $filteredResults = @()
    foreach( $result in $results )
    {
        if( ($result.BuildUser -like $Tags) -or
            ($result.BuildMachine -like $Tags) -or
            ($result.TestName -like $Tags) -or
            ($result.BuildURL -like $Tags ) )
            {
                $filteredResults += $result
            }
    }
    $results = $filteredResults
}

#Finally compute ages for 'Undefined' ages when -IncludeAge switch is being used.
#If this option is used, we will retrieve details from the blob or managed disk.
if( $IncludeAge )
{
    foreach( $result in $results )
    {
        if( $result.Age -eq "Undefined" )
        {
            $result.PsObject.Properties.Remove( 'Age' )
            $result | Add-Member Age $(Get-VMAgeFromDisk $result.vm)
        }
        $result.PsObject.Properties.Remove( 'vm' )
    }
}
#output the table
$results | Format-Table -Property VMname, Region, Size, Age, BuildUser, TestName, ResourceGroupName
