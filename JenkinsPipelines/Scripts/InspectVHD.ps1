Param (
    $RemoteFolder = "Z:\ReceivedFiles",
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
    
    #region VALIDATE ARGUMENTS
    if ( $env:CustomVHD -or $env:CustomVHDURL)
    {
        if ( $env:CustomVHDURL )
        {
            $DestinationFile = "$(Split-Path -Path $env:CustomVHDURL -Leaf)"
            Import-Module BitsTransfer -Force
            $WorkingDirectory = (Get-Location).Path
            LogMsg "Downloading $env:CustomVHDURL to '$WorkingDirectory\$DestinationFile'"
            $DownloadJob = Start-BitsTransfer -Source "$env:CustomVHDURL" -Asynchronous -Destination "$WorkingDirectory\$DestinationFile" -TransferPolicy Unrestricted -TransferType Download -Priority High
            $DownloadJobStatus = Get-BitsTransfer -JobId $DownloadJob.JobId
            Start-Sleep -Seconds 1
            LogMsg "JobID: $($DownloadJob.JobId)"
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
            }
            else
            {
                LogMsg "Download status : $($DownloadJobStatus.JobState)"
            }
            if (Test-Path $DestinationFile)
            {
                $CurrentVHD = $DestinationFile
                Rename-Item -Path $CurrentVHD  -NewName "$env:UpstreamBuildNumber-$CurrentVHD" -Verbose
                LogMsg "Download progress: Completed"
            }
            else 
            {
                $ExitCode = 1
                LogError "$DestinationFile is not present. Is the CustomVHDURL a valid link?"  
            }            
        }
        else 
        {
            $CurrentVHD = $env:CustomVHD
        }
        if ( ($CurrentVHD).EndsWith(".xz") -or ($CurrentVHD).EndsWith(".vhd") -or ($CurrentVHD).EndsWith(".vhdx"))
        {
            $ReceivedFile = "$env:UpstreamBuildNumber-$CurrentVHD"
            if ($env:CustomVHDURL)
            {
                LogMsg "Moving downloaded $ReceivedFile --> $CurrentLocalFolder."
                $Out = Move-Item -Path $ReceivedFile -Destination $CurrentLocalFolder -Force
            }
            else 
            {
                LogMsg "Copying received $ReceivedFile --> $CurrentLocalFolder."
                Copy-Item -Path "$CurrentRemoteFolder\$ReceivedFile" -Destination "$CurrentLocalFolder\$ReceivedFile" -Force                
            }
            if ($ReceivedFile.EndsWith(".xz"))
            {
                $WorkingDirectory = (Get-Location).Path
                Set-Location $CurrentLocalFolder
                LogMsg "Detected *.xz file."
                LogMsg "Extracting '$ReceivedFile'. Please wait..."
                $7zConsoleOuput = Invoke-Expression -Command "$7zExePath -y x '$ReceivedFile';" -Verbose
                if ($7zConsoleOuput -imatch "Everything is Ok")
                {
                    LogMsg "Extraction completed."
                    $NewVHDName = $(($ReceivedFile).TrimEnd("xz").TrimEnd("."))
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
                    ThrowException "Failed to extract $ReceivedFile."
                }
            }
            else 
            {
                $NewVHDName = $ReceivedFile  
            }
            if ($NewVHDName.EndsWith(".vhdx"))
            {
                $WorkingDirectory = $pwd
                Set-Location $CurrentLocalFolder            
                $NewVHDxName = $NewVHDName
                $NewVHDName = $NewVHDxName.Replace(".vhdx",".vhd")
                LogMsg "Converting '$NewVHDxName' --> '$NewVHDName'. [VHDx to VHD]"
                $convertJob = Start-Job -ScriptBlock { Convert-VHD -Path $args[0] -DestinationPath $args[1] -VHDType Dynamic } -ArgumentList "$CurrentLocalFolder\$NewVHDxName", "$CurrentLocalFolder\$NewVHDName"
                while ($convertJob.State -eq "Running")
                {
                    LogMsg "'$NewVHDxName' --> '$NewVHDName' is running"
                    Start-Sleep -Seconds 10
                }
                if ( $convertJob.State -eq "Completed")
                {
                    LogMsg "'$NewVHDxName' --> '$NewVHDName' is Succeeded."
                    $ExitCode = 0
                    LogMsg "Removing '$NewVHDxName'..."
                    Remove-Item "$CurrentLocalFolder\$NewVHDxName" -Force -ErrorAction SilentlyContinue
                }
                else
                {
                    LogMsg "'$NewVHDxName' --> '$NewVHDName' is Failed."
                    $ExitCode += 1
                }
                Set-Location $WorkingDirectory                
            }        
            ValidateVHD -vhdPath "$CurrentLocalFolder\$NewVHDName"
            Set-Content -Value "$NewVHDName" -Path .\CustomVHD.azure.env -NoNewline -Force
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
        LogError "Did you forgot to provide value for 'CustomVHD' parameter?"
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