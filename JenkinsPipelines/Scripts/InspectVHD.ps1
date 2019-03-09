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
    $LocalFolder = "Q:\Temp",
    $LogFileName = "InspectVHD.log",
    $XMLSecretFile = ""
)

Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

$CurrentRemoteFolder = "$RemoteFolder\$env:JenkinsUser"
$CurrentLocalFolder = "$LocalFolder"

$ExitCode = 0
try
{
    #Download the tools required for LISAv2 execution.
    Get-LISAv2Tools -XMLSecretFile $XMLSecretFile

    $7zExePath = (Get-Item .\Tools\7za.exe).FullName

    #Prerequisites:
    if (!(Test-Path $CurrentLocalFolder))
    {
        New-Item -Path $CurrentLocalFolder -ItemType Directory -Force | Out-Null
    }
    Write-LogInfo "Directory : $CurrentLocalFolder is available."
    $WorkingDirectory = (Get-Location).Path

    #region VALIDATE ARGUMENTS
    if ( $env:CustomVHD -or $env:CustomVHDURL)
    {
        if ( $env:CustomVHDURL )
        {
            $SourceVHDName = "$(Split-Path -Path $env:CustomVHDURL -Leaf)"
            if ($SourceVHDName -imatch '`?')
            {
                $SourceVHDName = $SourceVHDName.Split('?')[0]
            }
            $SourceVHDName = Remove-InvalidCharactersFromFileName -FileName $SourceVHDName
            $CurrentVHD = "$LocalFolder\$env:UpstreamBuildNumber-$SourceVHDName"
            $ReceivedVHD = "$CurrentRemoteFolder\$SourceVHDName"
            if (Test-Path $ReceivedVHD)
            {
                Write-LogInfo "$SourceVHDName File was already downloaded."
                Write-LogInfo "Copying $ReceivedVHD --> $CurrentVHD..."
                Copy-Item -Path $ReceivedVHD -Destination $CurrentVHD -Force
                Write-LogInfo "Copy Completed."
            }
            else
            {
                Write-LogInfo "$CurrentVHD file not present locally."
                Import-Module BitsTransfer -Force

                #Region Download the VHD.
                Write-LogInfo "Downloading $env:CustomVHDURL to '$LocalFolder\$SourceVHDName'"
                $DownloadJob = Start-BitsTransfer -Source "$env:CustomVHDURL" -Asynchronous -Destination "$LocalFolder\$SourceVHDName" -TransferPolicy Unrestricted -TransferType Download -Priority Foreground
                $DownloadJobStatus = Get-BitsTransfer -JobId $DownloadJob.JobId
                Start-Sleep -Seconds 1
                Write-LogInfo "JobID: $($DownloadJob.JobId)"
                while ($DownloadJobStatus.JobState -eq "Connecting" -or $DownloadJobStatus.JobState -eq "Transferring" -or $DownloadJobStatus.JobState -eq "Queued" -or $DownloadJobStatus.JobState -eq "TransientError" )
                {
                    $DownloadProgress = 100 - ((($DownloadJobStatus.BytesTotal - $DownloadJobStatus.BytesTransferred) / $DownloadJobStatus.BytesTotal) * 100)
                    $DownloadProgress = [math]::Round($DownloadProgress,2)
                    Write-LogInfo "Download '$($DownloadJobStatus.JobState)': $DownloadProgress%"
                    Start-Sleep -Seconds 2
                }
                if ($DownloadJobStatus.JobState -eq "Transferred")
                {
                    Write-LogInfo "Finalizing downloaded file..."
                    Complete-BitsTransfer -BitsJob $DownloadJob
                }
                else
                {
                    Write-LogInfo "Download status : $($DownloadJobStatus.JobState)"
                }
                #endregion

                if (Test-Path "$LocalFolder\$SourceVHDName")
                {
                    Write-LogInfo "Download progress: Completed"

                    #Copy VHD to remote received files -
                    Write-LogInfo "Copying $SourceVHDName --> $ReceivedVHD for future use."
                    Copy-Item -Path $LocalFolder\$SourceVHDName -Destination $ReceivedVHD -Force

                    #Move VHD to Local Temp Folder.
                    Write-LogInfo "Moving $SourceVHDName --> $CurrentVHD for current use."
                    Move-Item -Path $LocalFolder\$SourceVHDName -Destination $CurrentVHD -Force
                }
                else
                {
                    $ExitCode += 1
                    Write-LogErr "$SourceVHDName is not present. Is the CustomVHDURL a valid link?"
                    $DownloadJob = Remove-BitsTransfer -BitsJob $DownloadJob
                    Write-LogInfo "JobID: $($DownloadJob.JobId) Removed."
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
                Write-LogInfo "$SourceVHDName File was present in local storage."
                Write-LogInfo "Copying $ReceivedVHD --> $CurrentVHD for current use.."
                Copy-Item -Path $ReceivedVHD -Destination $CurrentVHD -Force
                Write-LogInfo "Copy Completed."
            }
            else
            {
                Write-LogInfo "We're not able to find $ReceivedVHD. Did uploade went successful?"
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
                    Write-LogInfo "Detected *.xz file."
                    Write-LogInfo "Extracting '$FilenameToExtract'. Please wait..."
                    $7zConsoleOuput = Invoke-Expression -Command "$7zExePath -y x '$FilenameToExtract';" -Verbose
                    if ($7zConsoleOuput -imatch "Everything is Ok")
                    {
                        Write-LogInfo "Extraction completed."
                        $CurrentVHD = $CurrentVHD.TrimEnd("xz").TrimEnd(".")
                        Write-LogInfo "Changing working directory to $WorkingDirectory"
                        Set-Location $WorkingDirectory
                        $VhdActualSize = ($7zConsoleOuput -imatch "size").Replace(" ",'').Replace(" ",'').Replace(" ",'').Replace(" ",'').Split(":")[1]
                        $VhdCompressedSize = ($7zConsoleOuput -imatch "Compressed").Replace(" ",'').Replace(" ",'').Replace(" ",'').Replace(" ",'').Split(":")[1]
                        $CompressinRatio = ((($VhdCompressedSize/($VhdActualSize-$VhdCompressedSize))*100))
                        Write-LogInfo "Compression Ratio : $([math]::Round($CompressinRatio,2))%"
                    }
                    else
                    {
                        $ExitCode += 1
                        Raise-Exception "Failed to extract $FilenameToExtract."
                    }
                }
                #endregion

                if ($CurrentVHD.EndsWith(".vhdx"))
                {
                    Set-Location $CurrentLocalFolder
                    $vhdx = $CurrentVHD | Split-Path -Leaf
                    $vhd = $vhdx.TrimEnd("x")
                    Write-LogInfo "Converting '$vhdx' --> '$vhd'. [VHDx to VHD]"
                    $convertJob = Start-Job -ScriptBlock { Convert-VHD -Path $args[0] -DestinationPath $args[1] -VHDType Dynamic } -ArgumentList "$CurrentLocalFolder\$vhdx", "$CurrentLocalFolder\$vhd"
                    while ($convertJob.State -eq "Running")
                    {
                        Write-LogInfo "'$vhdx' --> '$vhd' is running"
                        Start-Sleep -Seconds 10
                    }
                    if ( $convertJob.State -eq "Completed")
                    {
                        Write-LogInfo "$CurrentVHD Created suceessfully."
                        $CurrentVHD = $CurrentVHD.TrimEnd("x")
                        Write-LogInfo "'$vhdx' --> '$vhd' is Succeeded."
                        Write-LogInfo "Removing '$vhdx'..."
                        Remove-Item "$CurrentLocalFolder\$vhdx" -Force -ErrorAction SilentlyContinue
                    }
                    else
                    {
                        Write-LogInfo "'$vhdx' --> '$vhd' is Failed."
                        $ExitCode += 1
                    }
                    Set-Location $WorkingDirectory
                }
                Validate-VHD -vhdPath $CurrentVHD
                Set-Content -Value "$($CurrentVHD | Split-Path -Leaf)" -Path .\CustomVHD.azure.env -NoNewline -Force
            }
            else
            {
                $FileExtension = [System.IO.Path]::GetExtension("$CurrentVHD")
                Write-LogErr "Unsupported file type: *$FileExtension"
                $ExitCode += 1
            }
        }
        else
        {
            Write-LogErr "$CurrentVHD is not found. Exiting."
            $ExitCode = 1
        }
    }
    else
    {
        Write-LogErr "Did you forgot to provide value for 'CustomVHD' parameter?"
        $ExitCode += 1
    }
}
catch
{
    Raise-Exception($_)
}
finally
{
    Write-LogInfo "Exiting with code : $ExitCode"
    exit $ExitCode
}
