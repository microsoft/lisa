Param (
    $RemoteFolder = "Z:\ReceivedFiles",
    $LocalFolder = "D:\Temp"
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
    if ( $env:CustomVHD)
    {
        if ( ($env:CustomVHD).EndsWith(".xz") -or ($env:CustomVHD).EndsWith(".vhd") -or ($env:CustomVHD).EndsWith(".vhdx"))
        {
            $ReceivedFile = "$env:UpstreamBuildNumber-$env:CustomVHD"
            LogMsg "Copying $ReceivedFile --> $CurrentLocalFolder."
            Copy-Item -Path "$CurrentRemoteFolder\$ReceivedFile" -Destination "$CurrentLocalFolder\$ReceivedFile" -Force
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
        }
        else 
        {
            $FileExtension = [System.IO.Path]::GetExtension("$env:CustomVHD") 
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