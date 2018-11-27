##############################################################################################
# ManageTestStorageAccounts.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    This script copies VHD file to another storage account.
    This script will do Create / Delete operation for storage accounts
    mentioned in .\XML\RegionAndStorageAccounts.xml

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
    [string]$RGIdentifier="LISAv2",
    [switch]$Create,
    [switch]$Delete=$true
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

try
{
    if ( ( $Create -or $Delete ) -and !($Create -and $Delete))
    {
        if ( $Delete )
        {
            $Passphrase = Get-Random -Minimum 11111 -Maximum 999999
            Write-LogInfo "*****************************************CAUTION*****************************************"
            Write-LogInfo "You will be cleaniup all storage account mentioned in .\XML\RegionAndStorageAccounts.xml"
            Write-LogInfo "There is no way to recover the data from deleted storage accounts."
            Write-LogInfo "****************************************************************************************"
            $Choice = Read-Host -Prompt "Type $Passphrase to confirm"
            if ( $Choice -eq $Passphrase)
            {
                Write-LogInfo "Proceeding for cleanup..."
            }
            else
            {
                Write-LogInfo "You entered wrong number. Exiting."
                exit 0
            }
        }
        $AllAvailableRegions = (Get-AzureRmLocation | Where-Object { $_.Providers -imatch "Microsoft.Compute" }).Location
        $RegionStorageMapping = [xml](Get-Content .\XML\RegionAndStorageAccounts.xml)
        foreach ( $Region in $AllAvailableRegions)
        {
            if ( $RegionStorageMapping.AllRegions.$Region.StandardStorage -or $RegionStorageMapping.AllRegions.$Region.PremiumStorage )
            {
                $ResourceGroupName = "$RGIdentifier-storage-$Region"
                if ( $Create )
                {
                    $Out = Get-AzureRmResourceGroup -Name $ResourceGroupName -ErrorAction SilentlyContinue
                    if ( ! $Out.ResourceGroupName )
                    {
                        Write-LogInfo "$ResourceGroupName creating..."
                        $Out = New-AzureRmResourceGroup -Name $ResourceGroupName -Location $Region -ErrorAction SilentlyContinue
                        if ($Out.ProvisioningState -eq "Succeeded")
                        {
                            Write-LogInfo "$ResourceGroupName created successfully."
                        }
                    }
                    else
                    {
                        Write-LogInfo "$ResourceGroupName exists."
                    }
                    if ($RegionStorageMapping.AllRegions.$Region.StandardStorage)
                    {
                        Write-LogInfo "Creating Standard_LRS storage account : $($RegionStorageMapping.AllRegions.$Region.StandardStorage)"
                        $Out = New-AzureRmStorageAccount -ResourceGroupName $ResourceGroupName -Name $RegionStorageMapping.AllRegions.$Region.StandardStorage -SkuName Standard_LRS  -Location $Region
                        if ($out.ProvisioningState -eq "Succeeded")
                        {
                            Write-LogInfo "Creating Standard_LRS storage account : $($RegionStorageMapping.AllRegions.$Region.StandardStorage) : Succeeded"
                        }
                        else
                        {
                            Write-LogInfo "Creating Standard_LRS storage account : $($RegionStorageMapping.AllRegions.$Region.StandardStorage) : Failed"
                        }
                    }
                    if ($RegionStorageMapping.AllRegions.$Region.PremiumStorage)
                    {
                        Write-LogInfo "Creating Premium_LRS storage account : $($RegionStorageMapping.AllRegions.$Region.PremiumStorage)"
                        $Out = New-AzureRmStorageAccount -ResourceGroupName $ResourceGroupName -Name $RegionStorageMapping.AllRegions.$Region.PremiumStorage -SkuName Premium_LRS -Location $Region
                        if ($out.ProvisioningState -eq "Succeeded")
                        {
                            Write-LogInfo "Creating Premium_LRS storage account : $($RegionStorageMapping.AllRegions.$Region.PremiumStorage) : Succeeded"
                        }
                        else
                        {
                            Write-LogInfo "Creating Premium_LRS storage account : $($RegionStorageMapping.AllRegions.$Region.StandardStorage) : Failed"
                        }
                    }
                }
                elseif ($Delete)
                {
                    if ($RegionStorageMapping.AllRegions.$Region.StandardStorage)
                    {
                        Write-LogInfo "Removing Standard_LRS storage account : $($RegionStorageMapping.AllRegions.$Region.StandardStorage)"
                        Remove-AzureRmStorageAccount -ResourceGroupName $ResourceGroupName -Name $RegionStorageMapping.AllRegions.$Region.StandardStorage -Force  -Verbose
                    }
                    if ($RegionStorageMapping.AllRegions.$Region.PremiumStorage)
                    {
                        Write-LogInfo "Removing Premium_LRS storage account : $($RegionStorageMapping.AllRegions.$Region.PremiumStorage)"
                        Remove-AzureRmStorageAccount -ResourceGroupName $ResourceGroupName -Name $RegionStorageMapping.AllRegions.$Region.PremiumStorage -Force -Verbose
                    }
                    Write-LogInfo "Removing $ResourceGroupName"
                    Remove-AzureRMResourceGroup -Name $ResourceGroupName -Force -Verbose
                    $ExitCode = 0
                }
            }
        }
    }
    else
    {
        Write-LogInfo "Please provide either -Create or -Delete option."
    }

}
catch
{
    $ExitCode = 1
    Raise-Exception ($_)
}
finally
{
    Write-LogInfo "Exiting with code: $ExitCode"
    exit $ExitCode
}
#endregion
