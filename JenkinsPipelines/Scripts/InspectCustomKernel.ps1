Param (
    $RemoteFolder = "Z:\ReceivedFiles",
    $LocalFolder = "."
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

$CurrentRemoteFolder = "$RemoteFolder\$env:JenkinsUser"
$CurrentLocalFolder = "$LocalFolder"

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
        if ($env:Kernel -eq "default")
        {
            LogMsg "Overriding CustomKernelFile."
        }        
        if ( ($env:CustomKernelFile).EndsWith(".deb") -or ($env:CustomKernelFile).EndsWith(".rpm") )
        {
            $ReceivedFile = "$CurrentRemoteFolder\$env:UpstreamBuildNumber-$env:CustomKernelFile"
            if (Test-Path $ReceivedFile)
            {
                $KernelFile = Split-Path $ReceivedFile -Leaf
                LogMsg "Copying $ReceivedFile --> $CurrentLocalFolder."
                $out = Copy-Item -Path $ReceivedFile -Destination "$KernelFile" -Force
                LogMsg "Saving $KernelFile to CustomKernel.azure.env"
                $out = Set-Content -Value "$KernelFile" -Path CustomKernel.azure.env -Force -NoNewline
                $ExitCode = 0
            }
            else 
            {
                $ExitCode = 1
                LogError "$ReceivedFile is not present. Did you forgot to upload it?"  
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
        if ($env:Kernel -eq "default")
        {
            LogMsg "Overriding CustomKernelURL."
        }         
        $DestinationFile = "$(Split-Path -Path $env:CustomKernelURL -Leaf)"
        Import-Module BitsTransfer -Force
        $WorkingDirectory = (Get-Location).Path
        LogMsg "Downloading $env:CustomKernelURL to '$WorkingDirectory\$DestinationFile'"
        $DownloadJob = Start-BitsTransfer -Source "$env:CustomKernelURL" -Asynchronous -Destination "$WorkingDirectory\$DestinationFile" -TransferPolicy Unrestricted -TransferType Download -Priority High
        $DownloadJobStatus = Get-BitsTransfer -JobId $DownloadJob.JobId
        Start-Sleep -Seconds 1
        while ($DownloadJobStatus.JobState -eq "Connecting" -or $DownloadJobStatus.JobState -eq "Transferring") 
        {
            $DownloadProgress = 100 - ((($DownloadJobStatus.BytesTotal - $DownloadJobStatus.BytesTransferred) / $DownloadJobStatus.BytesTotal) * 100)
            $DownloadProgress = [math]::Round($DownloadProgress,2)
            LogMsg "Download progress: $DownloadProgress%"
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
        if (Test-Path $DestinationFile)
        {
            $KernelFile = "$env:UpstreamBuildNumber-$DestinationFile"
            LogMsg "Renaming $DestinationFile --> $KernelFile."
            $Out = Rename-Item -Path $DestinationFile -NewName $KernelFile
            LogMsg "Saving $KernelFile to CustomKernel.azure.env"
            $out = Set-Content -Value "$KernelFile" -Path CustomKernel.azure.env -Force -NoNewline
            $ExitCode = 0            
        }
        else 
        {
            $ExitCode = 1
            LogError "$DestinationFile is not present. Is the CustomKernelURL a valid link?"  
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