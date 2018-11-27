##############################################################################################
# ReceivePartnerFiles.ps1
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

param (
    [string]$SharedParentDirectory = "J:\ReceivedFiles",
    [string]$LogFileName = "ReceivePartnerFiles.log",
    [string]$PartnerUsername
)

Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force

#Import Libraries
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }
Get-ChildItem .\JenkinsPipelines\Scripts -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }
Import-Module BitsTransfer -Force

$ExitCode = 0

$PartnerUsernameShareDirectory = "$SharedParentDirectory\$PartnerUsername"


if (!(Test-Path $SharedParentDirectory))
{
    Write-LogInfo "Creating $SharedParentDirectory."
    New-Item -ItemType Directory -Path $SharedParentDirectory -Force -Verbose | Out-Null
}
else
{
    Write-LogInfo "$SharedParentDirectory available."
}
if(!(Test-Path $PartnerUsernameShareDirectory))
{
    Write-LogInfo "Creating $PartnerUsernameShareDirectory."
    New-Item -ItemType Directory -Path $PartnerUsernameShareDirectory -Force -Verbose  | Out-Null
}
else
{
    Write-LogInfo "$PartnerUsernameShareDirectory available."

}
if (!$env:ImageSource -and !$env:CustomVHD -and !$env:CustomVHDURL)
{
    Write-LogInfo "---------------------------------------------------------------------"
    Write-LogInfo "Error: Please upload a VHD file or choose ImageSource from the list."
    Write-LogInfo "---------------------------------------------------------------------"
    $ExitCode += 1
    exit $ExitCode
}
if ( ( $env:ImageSource -and $env:ImageSource -inotmatch "Select a" ) -and $env:CustomVHD )
{
    Write-LogInfo "---------------------------------------------------------------------"
    Write-LogInfo "Error: You have chosen Azure Image + uploaded VHD file. This is not supported."
    Write-LogInfo "You can start separate jobs to achieve this."
    Write-LogInfo "$env:ImageSource"
    Write-LogInfo "---------------------------------------------------------------------"
    $ExitCode += 1
    exit $ExitCode
}

if ( (($env:CustomKernelFile -ne $null) -or ($env:customKernelURL -ne $null)) -and ($env:Kernel -ne "custom"))
{
    Write-LogInfo "---------------------------------------------------------------------"
    Write-LogInfo "Error: You've given custom kernel URL / local file."
    Write-LogInfo "Please also select 'custom' value for Kernel parameter to confirm this."
    Write-LogInfo "---------------------------------------------------------------------"
    $ExitCode += 1
    exit $ExitCode
}
if ($env:Kernel -eq "custom")
{
    if (($env:CustomKernelFile -eq $null) -and ($env:customKernelURL -eq $null))
    {
        Write-LogInfo "---------------------------------------------------------------------"
        Write-LogInfo "Error: You selected 'custom' Kernel but didn't provide kernel file or Kernel URL."
        Write-LogInfo "---------------------------------------------------------------------"
        $ExitCode += 1
        exit $ExitCode
    }
    if ($env:CustomKernelFile)
    {
        if (!($env:CustomKernelFile.EndsWith(".deb")) -and !($env:CustomKernelFile.EndsWith(".rpm")))
        {
            Write-LogInfo "-----------------------------------------------------------------------------------------------------------"
            Write-LogInfo "Error: .$($env:CustomKernelFile.Split(".")[$env:CustomKernelFile.Split(".").Count -1]) file is not supported."
            Write-LogInfo "-----------------------------------------------------------------------------------------------------------"
            $ExitCode += 1
            exit $exitCodea
        }
        else
        {
            $TestKernel = "$env:CustomKernelFile"
            Write-LogInfo "Renaming CustomKernelFile --> $TestKernel"
            Rename-Item -Path CustomKernelFile -NewName $TestKernel
        }
    }
    if ($env:customKernelURL)
    {
        if (!($env:customKernelURL.EndsWith(".deb")) -and !($env:customKernelURL.EndsWith(".rpm")))
        {
            Write-LogInfo "-----------------------------------------------------------------------------------------------------------"
            Write-LogInfo "Error: .$($env:customKernelURL.Split(".")[$env:customKernelURL.Split(".").Count -1]) file is NOT supported."
            Write-LogInfo "-----------------------------------------------------------------------------------------------------------"
            $ExitCode += 1
            exit $ExitCode
        }
    }
}
if ($TestKernel)
{
    Write-LogInfo "Moving $TestKernel --> $PartnerUsernameShareDirectory\$TestKernel"
    Move-Item $TestKernel $PartnerUsernameShareDirectory\$TestKernel -Force
}
if ($env:CustomVHD)
{
    Write-LogInfo "VHD: $env:CustomVHD"
    $TempVHD = ($env:CustomVHD).ToLower()
    if ( $TempVHD.EndsWith(".vhd") -or $TempVHD.EndsWith(".vhdx") -or $TempVHD.EndsWith(".xz"))
    {
        Write-LogInfo "Moving '$env:CustomVHD' --> $PartnerUsernameShareDirectory\$env:CustomVHD"
        Move-Item CustomVHD $PartnerUsernameShareDirectory\$env:CustomVHD -Force
        $ExitCode = 0
    }
    else
    {
        Write-LogInfo "-----------------ERROR-------------------"
        Write-LogInfo "Error: Filetype : $($TempVHD.Split(".")[$TempVHD.Split(".").Count -1]) is NOT supported."
        Write-LogInfo "Supported file types : vhd, vhdx, xz."
        Write-LogInfo "-----------------------------------------"
        $ExitCode = 1
    }
}
if ($env:ImageSource)
{
    Write-LogInfo "ImageSource: $env:ImageSource"
}
exit $ExitCode
