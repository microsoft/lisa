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
    [string]$PartnerUsername
)

#Import Libraries
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
Get-ChildItem .\JenkinsPipelines\Scripts -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
Import-Module BitsTransfer -Force

$BuildNumber = $env:BUILD_NUMBER
$ExitCode = 0

$PartnerUsernameShareDirectory = "$SharedParentDirectory\$PartnerUsername"


if (!(Test-Path $SharedParentDirectory))
{
    LogMsg "Creating $SharedParentDirectory."
    New-Item -ItemType Directory -Path $SharedParentDirectory -Force -Verbose | Out-Null
}
else
{
    LogMsg "$SharedParentDirectory available."
}
if(!(Test-Path $PartnerUsernameShareDirectory))
{
    LogMsg "Creating $PartnerUsernameShareDirectory."
    New-Item -ItemType Directory -Path $PartnerUsernameShareDirectory -Force -Verbose  | Out-Null
}
else
{
    LogMsg "$PartnerUsernameShareDirectory available."

}
if (!$env:ImageSource -and !$env:CustomVHD -and !$env:CustomVHDURL)
{
    LogMsg "---------------------------------------------------------------------"
    LogMsg "Error: Please upload a VHD file or choose ImageSource from the list."
    LogMsg "---------------------------------------------------------------------"
    $ExitCode += 1
    exit $ExitCode
}
if ( ( $env:ImageSource -and $env:ImageSource -inotmatch "Select a" ) -and $env:CustomVHD )
{
    LogMsg "---------------------------------------------------------------------"
    LogMsg "Error: You have chosen Azure Image + uploaded VHD file. This is not supported."
    LogMsg "You can start separate jobs to achieve this."
    LogMsg "$env:ImageSource"
    LogMsg "---------------------------------------------------------------------"
    $ExitCode += 1
    exit $ExitCode
}

if ( (($env:CustomKernelFile -ne $null) -or ($env:customKernelURL -ne $null)) -and ($env:Kernel -ne "custom"))
{
    LogMsg "---------------------------------------------------------------------"
    LogMsg "Error: You've given custom kernel URL / local file."
    LogMsg "Please also select 'custom' value for Kernel parameter to confirm this."
    LogMsg "---------------------------------------------------------------------"
    $ExitCode += 1
    exit $ExitCode   
}
if ($env:Kernel -eq "custom")
{
    if (($env:CustomKernelFile -eq $null) -and ($env:customKernelURL -eq $null))
    {
        LogMsg "---------------------------------------------------------------------"
        LogMsg "Error: You selected 'custom' Kernel but didn't provide kernel file or Kernel URL."
        LogMsg "---------------------------------------------------------------------"
        $ExitCode += 1
        exit $ExitCode          
    }
    if ($env:CustomKernelFile)
    {
        if (!($env:CustomKernelFile.EndsWith(".deb")) -and !($env:CustomKernelFile.EndsWith(".rpm")))
        {
            LogMsg "-----------------------------------------------------------------------------------------------------------"
            LogMsg "Error: .$($env:CustomKernelFile.Split(".")[$env:CustomKernelFile.Split(".").Count -1]) file is not supported."
            LogMsg "-----------------------------------------------------------------------------------------------------------"
            $ExitCode += 1
            exit $exitCodea
        }
        else
        {
            $TestKernel = "$env:CustomKernelFile"
            LogMsg "Renaming CustomKernelFile --> $TestKernel"
            Rename-Item -Path CustomKernelFile -NewName $TestKernel
        }
    } 
    if ($env:customKernelURL)
    {
        if (!($env:customKernelURL.EndsWith(".deb")) -and !($env:customKernelURL.EndsWith(".rpm")))
        {
            LogMsg "-----------------------------------------------------------------------------------------------------------"
            LogMsg "Error: .$($env:customKernelURL.Split(".")[$env:customKernelURL.Split(".").Count -1]) file is NOT supported."
            LogMsg "-----------------------------------------------------------------------------------------------------------"
            $ExitCode += 1
            exit $ExitCode
        }
    }       
}
if ($TestKernel)
{
    LogMsg "Moving $TestKernel --> $PartnerUsernameShareDirectory\$TestKernel"
    Move-Item $TestKernel $PartnerUsernameShareDirectory\$TestKernel -Force
}
if ($env:CustomVHD)
{
    LogMsg "VHD: $env:CustomVHD"
    $TempVHD = ($env:CustomVHD).ToLower()
    if ( $TempVHD.EndsWith(".vhd") -or $TempVHD.EndsWith(".vhdx") -or $TempVHD.EndsWith(".xz"))
    {
        LogMsg "Moving '$env:CustomVHD' --> $PartnerUsernameShareDirectory\$env:CustomVHD"
        Move-Item CustomVHD $PartnerUsernameShareDirectory\$env:CustomVHD -Force
        $ExitCode = 0
    }
    else
    {
        LogMsg "-----------------ERROR-------------------"
        LogMsg "Error: Filetype : $($TempVHD.Split(".")[$TempVHD.Split(".").Count -1]) is NOT supported."
        LogMsg "Supported file types : vhd, vhdx, xz."
        LogMsg "-----------------------------------------"
        $ExitCode = 1
    }
}
if ($env:ImageSource)
{
    LogMsg "ImageSource: $env:ImageSource"
}
exit $ExitCode