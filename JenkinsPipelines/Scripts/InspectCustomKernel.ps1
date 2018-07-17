##############################################################################################
# InspectCustomKernel.ps1
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

Param (
    $RemoteFolder = "J:\ReceivedFiles",
    $LocalFolder = "."
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

$CurrentRemoteFolder = "$RemoteFolder\$env:JenkinsUser"
$CurrentLocalFolder = "$LocalFolder"
$WorkingDirectory = (Get-Location).Path

$ExitCode = 0
try
{

    #Prerequisites:
    if (!(Test-Path $CurrentLocalFolder))
    {
        New-Item -Path $CurrentLocalFolder -ItemType Directory -Force | Out-Null
    }
    LogMsg "Directory : $CurrentLocalFolder is available."
    
    #region VALIDATE ARGUMENTS
    if ( $env:CustomKernelFile -and $env:CustomKernelURL )
    {
        LogMsg "Please provide either 'CustomKernelFile' or 'CustomKernelURL'."
        LogMsg "Aborting."
        $ExitCode = 1
    }
    elseif ( $env:CustomKernelFile)
    {        
        if ( ($env:CustomKernelFile).EndsWith(".deb") -or ($env:CustomKernelFile).EndsWith(".rpm") )
        {
            $CurrentKernel = "$CurrentLocalFolder\$env:UpstreamBuildNumber-$env:CustomKernelFile"
            $ReceivedKernel = "$CurrentRemoteFolder\$env:CustomKernelFile"
            if (Test-Path $ReceivedKernel)
            {
                LogMsg "Copying $ReceivedKernel --> $CurrentKernel for current use..."
                $out = Copy-Item -Path $ReceivedKernel -Destination "$CurrentKernel" -Force
                $KernelFile = Split-Path $CurrentKernel -Leaf

                LogMsg "Saving $KernelFile to CustomKernel.azure.env"
                $out = Set-Content -Value "$KernelFile" -Path CustomKernel.azure.env -Force -NoNewline
                $ExitCode = 0
            }
            else 
            {
                $ExitCode = 1
                LogError "$ReceivedKernel is not present. Did you forgot to upload it?"  
            }
        }
        else 
        {
            $FileExtension = [System.IO.Path]::GetExtension("$env:CustomKernelFile") 
            LogError "Unsupported file type: *$FileExtension"
            $ExitCode += 1
        }
    }
    elseif ( $env:CustomKernelURL )
    {
        if ( ($env:CustomKernelURL).EndsWith(".deb") -or ($env:CustomKernelURL).EndsWith(".rpm") )
        {
            $SourceKernelName = "$(Split-Path -Path $env:CustomKernelURL -Leaf)"
            $CurrentKernel = "$CurrentLocalFolder\$env:UpstreamBuildNumber-$SourceKernelName"
            $ReceivedKernel = "$CurrentRemoteFolder\$SourceKernelName"
            
            if (Test-Path $ReceivedKernel)
            {
                LogMsg "$SourceKernelName File was already downloaded."
                LogMsg "Copying $ReceivedKernel --> $CurrentKernel for current use..."
                Copy-Item -Path "$ReceivedKernel" -Destination $CurrentKernel -Force
                $KernelFile = $CurrentKernel  | Split-Path -Leaf
                LogMsg "Saving $KernelFile to CustomKernel.azure.env"
                $out = Set-Content -Value "$KernelFile" -Path CustomKernel.azure.env -Force -NoNewline
                $ExitCode = 0
            }
            else 
            {
                #Import down module.
                Import-Module BitsTransfer -Force
    
                LogMsg "Downloading $env:CustomKernelURL to '$CurrentLocalFolder\$SourceKernelName'"
                $DownloadJob = Start-BitsTransfer -Source "$env:CustomKernelURL" -Asynchronous -Destination "$CurrentLocalFolder\$SourceKernelName" -TransferPolicy Unrestricted -TransferType Download -Priority High
                $DownloadJobStatus = Get-BitsTransfer -JobId $DownloadJob.JobId
                Start-Sleep -Seconds 1
                LogMsg "JobID: $($DownloadJob.JobId)"
                while ($DownloadJobStatus.JobState -eq "Connecting" -or $DownloadJobStatus.JobState -eq "Transferring" -or $DownloadJobStatus.JobState -eq "Queued" ) 
                {
                    $DownloadProgress = 100 - ((($DownloadJobStatus.BytesTotal - $DownloadJobStatus.BytesTransferred) / $DownloadJobStatus.BytesTotal) * 100)
                    $DownloadProgress = [math]::Round($DownloadProgress,2)
                    LogMsg "Download '$($DownloadJobStatus.JobState)': $DownloadProgress%"
                    Start-Sleep -Seconds 2
                }
                if ($DownloadJobStatus.JobState -eq "Transferred")
                {
                    LogMsg "Finalizing downloaded file..."
                    Complete-BitsTransfer -BitsJob $DownloadJob
                    LogMsg "Download progress: Completed"
                }
                else
                {
                    LogMsg "Download status : $($DownloadJobStatus.JobState)"
                }
                if (Test-Path "$CurrentLocalFolder\$SourceKernelName")
                {
                    LogMsg "Copying $CurrentLocalFolder\$SourceKernelName --> $ReceivedKernel for future use..."
                    Copy-Item -Path "$CurrentLocalFolder\$SourceKernelName" -Destination $ReceivedKernel -Force
    
                    LogMsg "Moving $CurrentLocalFolder\$SourceKernelName --> $CurrentKernel for current use..."
                    Move-Item -Path "$CurrentLocalFolder\$SourceKernelName" -Destination $CurrentKernel -Force
                    $KernelFile = $CurrentKernel  | Split-Path -Leaf
                    LogMsg "Saving $KernelFile to CustomKernel.azure.env"
                    $out = Set-Content -Value "$KernelFile" -Path CustomKernel.azure.env -Force -NoNewline
                    $ExitCode = 0
                }
                else 
                {
                    $ExitCode = 1
                    LogError "$SourceKernelName is not present. Is the CustomKernelURL a valid link?"  
                }            
            }
        }
        else
        {
            $FileExtension = [System.IO.Path]::GetExtension("$env:CustomKernelFile") 
            LogError "Unsupported file type: *$FileExtension"
            $ExitCode += 1            
        }        
    }
    else 
    {
        LogError "Did you forgot to provide value for 'CustomKernelFile' or 'CustomKernelURL' parameter?"
        $ExitCode = 1
    }
}
catch
{
    ThrowException($_)
}
finally
{
    LogMsg "Exiting with code : $ExitCode"
    exit $ExitCode
}