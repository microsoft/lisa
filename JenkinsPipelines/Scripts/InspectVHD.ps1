##############################################################################################
# InspectVHD.ps1
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
    $LocalFolder = "Q:\Temp"
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

$CurrentRemoteFolder = "$RemoteFolder\$env:JenkinsUser"
$CurrentLocalFolder = "$LocalFolder"

$ExitCode = 0
try
{
    $7zExePath = (Get-Item .\Tools\7za.exe).FullName

    #Prerequisites:
    if (!(Test-Path $CurrentLocalFolder))
    {
        New-Item -Path $CurrentLocalFolder -ItemType Directory -Force | Out-Null
    }
    LogMsg "Directory : $CurrentLocalFolder is available."
    $WorkingDirectory = (Get-Location).Path

    #region VALIDATE ARGUMENTS
    if ( $env:CustomVHD -or $env:CustomVHDURL)
    {
        if ( $env:CustomVHDURL )
        {
            $SourceVHDName = "$(Split-Path -Path $env:CustomVHDURL -Leaf)"
            $CurrentVHD = "$LocalFolder\$env:UpstreamBuildNumber-$SourceVHDName"
            $ReceivedVHD = "$CurrentRemoteFolder\$SourceVHDName"
            if (Test-Path $ReceivedVHD)
            {
                LogMsg "$SourceVHDName File was already downloaded."
                LogMsg "Copying $ReceivedVHD --> $CurrentVHD..."
                Copy-Item -Path $ReceivedVHD -Destination $CurrentVHD -Force
                LogMsg "Copy Completed."
            }
            else 
            {
                LogMsg "$CurrentVHD file not present locally."
                Import-Module BitsTransfer -Force

                #Region Download the VHD.
                LogMsg "Downloading $env:CustomVHDURL to '$LocalFolder\$SourceVHDName'"
                $DownloadJob = Start-BitsTransfer -Source "$env:CustomVHDURL" -Asynchronous -Destination "$LocalFolder\$SourceVHDName" -TransferPolicy Unrestricted -TransferType Download -Priority Foreground
                $DownloadJobStatus = Get-BitsTransfer -JobId $DownloadJob.JobId
                Start-Sleep -Seconds 1
                LogMsg "JobID: $($DownloadJob.JobId)"
                while ($DownloadJobStatus.JobState -eq "Connecting" -or $DownloadJobStatus.JobState -eq "Transferring" -or $DownloadJobStatus.JobState -eq "Queued" -or $DownloadJobStatus.JobState -eq "TransientError" ) 
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
                }
                else
                {
                    LogMsg "Download status : $($DownloadJobStatus.JobState)"
                }
                #endregion

                if (Test-Path "$LocalFolder\$SourceVHDName")
                {
                    LogMsg "Download progress: Completed"

                    #Copy VHD to remote received files - 
                    LogMsg "Copying $SourceVHDName --> $ReceivedVHD for future use."
                    Copy-Item -Path $LocalFolder\$SourceVHDName -Destination $ReceivedVHD -Force

                    #Move VHD to Local Temp Folder.
                    LogMsg "Moving $SourceVHDName --> $CurrentVHD for current use."
                    Move-Item -Path $LocalFolder\$SourceVHDName -Destination $CurrentVHD -Force
                }
                else 
                {
                    $ExitCode += 1
                    LogError "$SourceVHDName is not present. Is the CustomVHDURL a valid link?"
                    $DownloadJob = Remove-BitsTransfer -BitsJob $DownloadJob  
                    LogMsg "JobID: $($DownloadJob.JobId) Removed."
                }                
            }            
        }
        else 
        {
            $SourceVHDName = $env:CustomVHD
            $CurrentVHD = "$LocalFolder\$env:UpstreamBuildNumber-$SourceVHDName"
            $ReceivedVHD = "$CurrentRemoteFolder\$SourceVHDName"
            if (Test-Path $ReceivedVHD)
            {
                LogMsg "$SourceVHDName File was present in local storage."
                LogMsg "Copying $ReceivedVHD --> $CurrentVHD for current use.."
                Copy-Item -Path $ReceivedVHD -Destination $CurrentVHD -Force
                LogMsg "Copy Completed."
            }
            else 
            {
                LogMsg "We're not able to find $ReceivedVHD. Did uploade went successful?"
                $ExitCode += 1
            }
        }

        if ( Test-Path $CurrentVHD)
        {
            if ( ($CurrentVHD).EndsWith(".xz") -or ($CurrentVHD).EndsWith(".vhd") -or ($CurrentVHD).EndsWith(".vhdx"))
            {
                #region Extract the VHD if required.
                if ($CurrentVHD.EndsWith(".xz"))
                {
                    $FilenameToExtract = $CurrentVHD | Split-Path -Leaf
                    Set-Location $CurrentLocalFolder
                    LogMsg "Detected *.xz file."
                    LogMsg "Extracting '$FilenameToExtract'. Please wait..."
                    $7zConsoleOuput = Invoke-Expression -Command "$7zExePath -y x '$FilenameToExtract';" -Verbose
                    if ($7zConsoleOuput -imatch "Everything is Ok")
                    {
                        LogMsg "Extraction completed."
                        $CurrentVHD = $CurrentVHD.TrimEnd("xz").TrimEnd(".")
                        LogMsg "Changing working directory to $WorkingDirectory"
                        Set-Location $WorkingDirectory
                        $VhdActualSize = ($7zConsoleOuput -imatch "size").Replace(" ",'').Replace(" ",'').Replace(" ",'').Replace(" ",'').Split(":")[1]
                        $VhdCompressedSize = ($7zConsoleOuput -imatch "Compressed").Replace(" ",'').Replace(" ",'').Replace(" ",'').Replace(" ",'').Split(":")[1]
                        $CompressinRatio = ((($VhdCompressedSize/($VhdActualSize-$VhdCompressedSize))*100))
                        LogMsg "Compression Ratio : $([math]::Round($CompressinRatio,2))%"
                    }
                    else
                    {
                        $ExitCode += 1
                        ThrowException "Failed to extract $FilenameToExtract."
                    }
                }
                #endregion
    
                if ($CurrentVHD.EndsWith(".vhdx"))
                {
                    Set-Location $CurrentLocalFolder
                    $vhdx = $CurrentVHD | Split-Path -Leaf
                    $vhd = $vhdx.TrimEnd("x")
                    LogMsg "Converting '$vhdx' --> '$vhd'. [VHDx to VHD]"
                    $convertJob = Start-Job -ScriptBlock { Convert-VHD -Path $args[0] -DestinationPath $args[1] -VHDType Dynamic } -ArgumentList "$CurrentLocalFolder\$vhdx", "$CurrentLocalFolder\$vhd"
                    while ($convertJob.State -eq "Running")
                    {
                        LogMsg "'$vhdx' --> '$vhd' is running"
                        Start-Sleep -Seconds 10
                    }
                    if ( $convertJob.State -eq "Completed")
                    {
                        LogMsg "$CurrentVHD Created suceessfully."
                        $CurrentVHD = $CurrentVHD.TrimEnd("x")
                        LogMsg "'$vhdx' --> '$vhd' is Succeeded."
                        LogMsg "Removing '$vhdx'..."
                        Remove-Item "$CurrentLocalFolder\$vhdx" -Force -ErrorAction SilentlyContinue
                    }
                    else
                    {
                        LogMsg "'$vhdx' --> '$vhd' is Failed."
                        $ExitCode += 1
                    }
                    Set-Location $WorkingDirectory                
                }        
                ValidateVHD -vhdPath $CurrentVHD
                Set-Content -Value "$($CurrentVHD | Split-Path -Leaf)" -Path .\CustomVHD.azure.env -NoNewline -Force
            }
            else 
            {
                $FileExtension = [System.IO.Path]::GetExtension("$CurrentVHD") 
                LogError "Unsupported file type: *$FileExtension"
                $ExitCode += 1
            }
        }
        else 
        {
            LogError "$CurrentVHD is not found. Exiting."
            $ExitCode = 1             
        }
    }
    else 
    {
        LogError "Did you forgot to provide value for 'CustomVHD' parameter?"
        $ExitCode += 1 
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