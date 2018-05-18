param (
    [string]$SharedParentDirectory = "Z:\ReceivedFiles",
    [string]$PartnerUsername
)

#Import Libraries
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
Get-ChildItem .\JenkinsPipelines\Scripts -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
Import-Module BitsTransfer -Force

$BuildNumber = $env:BUILD_NUMBER
$ExitCode = 0

$BuildNumber

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

if ($env:ImageSource -eq $null -and $env:CustomVHD -eq $null)
{
    LogMsg "---------------------------------------------------------------------"
    LogMsg "Error: Please upload a VHD file or choose ImageSource from the list."
    LogMsg "---------------------------------------------------------------------"
    $ExitCode += 1
    exit $ExitCode
}
if ($env:ImageSource -eq $null -and $env:CustomVHD -eq $null)
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
            if ($env:CustomKernelFile.EndsWith(".deb"))
            {
                $TestKernel = "$BuildNumber-$env:CustomKernelFile"
                LogMsg "Renaming CustomKernelFile --> $TestKernel"
                Rename-Item -Path CustomKernelFile -NewName $TestKernel
            }
            if ($env:CustomKernelFile.EndsWith(".rpm"))
            {
                $TestKernel = "$BuildNumber-$env:CustomKernelFile"
                LogMsg "Renaming  CustomKernelFile --> $TestKernel"
                Rename-Item -Path CustomKernelFile -NewName $TestKernel
            }
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
        else
        {
            LogText "Downloading $($env:customKernelURL)"
            $out = Start-BitsTransfer  -Source "$env:customKernelURL"
            if ($?)
            {
                if ($env:customKernelURL.EndsWith(".deb"))
                {
                    $TestKernel = "$BuildNumber-$($env:customKernelURL.Split("/")[$env:customKernelURL.Split("/").Count -1])"
                    LogMsg "Renaming $($env:customKernelURL.Split("/")[$env:customKernelURL.Split("/").Count -1]) --> $TestKernel"
                    Rename-Item -Path $($env:customKernelURL.Split("/")[$env:customKernelURL.Split("/").Count -1]) -NewName $TestKernel
                }            
                if ($env:customKernelURL.EndsWith(".rpm"))
                {
                    $TestKernel = "$BuildNumber-$($env:customKernelURL.Split("/")[$env:customKernelURL.Split("/").Count -1])"
                    LogMsg "Renaming $($env:customKernelURL.Split("/")[$env:customKernelURL.Split("/").Count -1]) --> $TestKernel"
                    Rename-Item -Path $($env:customKernelURL.Split("/")[$env:customKernelURL.Split("/").Count -1]) -NewName $TestKernel
                }
            }
            else
            {
                LogMsg "--------------------------------------------------------------------------------------------------------------"
                LogText "ERROR: Failed to download $($env:customKernelURL). Please verify that your URL is accessible on public internet."
                LogMsg "--------------------------------------------------------------------------------------------------------------"
                $ExitCode += 1
                exit $ExitCode
            }
        }
    }       
}

#$PartnerUsernameShareDirectory = "$SharedParentDirectory\$PartnerName-files"
#$out = mkdir "$SharedParentDirectory\$PartnerName-files" -ErrorAction SilentlyContinue | Out-Null

if ($TestKernel)
{
    #$out = Start-BitsTransfer  -Source "https://github.com/iamshital/azure-linux-automation/raw/master/AddAzureRmAccountFromSecretsFile.ps1" 
    #$out = Start-BitsTransfer  -Source "https://github.com/iamshital/azure-linux-automation/raw/master/Extras/UploadFilesToStorageAccount.ps1"
    #.\UploadFilesToStorageAccount.ps1 -filePaths $TestKernel -destinationStorageAccount konkasoftpackages -destinationContainer partner -destinationFolder $PartnerName
    LogMsg "Copying $TestKernel --> $PartnerUsernameShareDirectory\$TestKernel"
    Move-Item $TestKernel $PartnerUsernameShareDirectory\$TestKernel -Force

}
if ($env:CustomVHD)
{
    LogMsg "VHD: $env:CustomVHD"
    $TempVHD = ($env:CustomVHD).ToLower()
    if ( $TempVHD.EndsWith(".vhd") -or $TempVHD.EndsWith(".vhdx") -or $TempVHD.EndsWith(".xz"))
    {
        

        LogMsg "Copying '$env:CustomVHD' --> $PartnerUsernameShareDirectory\$BuildNumber-$env:CustomVHD"
        Move-Item CustomVHD $PartnerUsernameShareDirectory\$BuildNumber-$env:CustomVHD -Force
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