# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param(
    [String] $FTPHost,
    [String] $FTPUser,
    [String] $FTPPass,
    [String] $SourceFolder,
    [String] $KernelName,
    [String] $Url
)

$CURRENT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

function Sync-Files {
    param(
        [string] $Username,
        [string] $Password,
        [String] $Hostname,
        [String] $SrcPath,
        [String] $DesPath
    )

    $chknuget = Get-PackageProvider -Name NuGet  -ErrorAction SilentlyContinue
    $ckwinscp = Get-InstalledModule -Name WinSCP  -ErrorAction SilentlyContinue
    if (-not $chknuget) {
        Write-Host "Instaling PackageProvider Nuget ..."
        $innuget = Install-PackageProvider -Name NuGet -Force
        if (-not $innuget) {
            Write-Error "Failed to install PackageProvider Nuget..."
        }
    }
    if (-not $ckwinscp) {
        Write-Host "Instaling WinSCP Powershell Wrapper..."
        $inwinscp = Install-Module -Name WinSCP  -Force
        if (-not $inwinscp) {
            Write-Error "Failed to install WinSCP Powershell Wrapper..."
        }
    }

    #Start
    Write-Host "Starting Connection to $Hostname ..."
    # Creating Credentials
    $secPass = $Password | ConvertTo-SecureString -AsPlainText -Force
    $Credential = New-Object System.Management.Automation.PSCredential -ArgumentList $Username, $secPass
    $Session = New-WinSCPSessionOption -HostName $Hostname -Credential $Credential -Protocol Ftp
    # Connect
    $Connection = New-WinSCPSession -SessionOption $Session
    if (-not $Connection) {
        Write-Host "Failed to Connect to $Hostname ..."
    }
    Write-Host "SRC: $SrcPath  DEST: $DesPath"
    $move = Send-WinSCPItem  -WinSCPSession $Connection  -Path $SrcPath -Destination $DesPath
    # Force param  will create directory
    if (-not $move) {
        Write-Error "Failed to preform FTP operation..."
    }
    # Remove the WinSCPSession after completion.
    Remove-WinSCPSession -WinSCPSession $Connection -ErrorAction SilentlyContinue
}

function Update-Coverage {
    param(
        [String] $SrcPath,
        [String] $Htmlloc,
        [String] $KernelName
    )
    Write-Host "Parsing coverage  ..."
    $fixfile = Get-Content "$SrcPath"; $fixfile[0] = "{"; $fixfile[-1] = "}"; $fixfile |Out-File "temp.js" -Encoding 'ASCII'
    if (!$fixfile) {
        Write-Error "Failed to change Encoding to UTF-8..."
    }
    #Python Should installed by default
    & "C:\Python27\python.exe" .\create_coverage_file.py "temp.js" $Htmlloc  "$KernelName" > $SrcPath

}

Function Main {

    Write-Host "Uploading files to date directory ..."
    $SrcDest = $(Get-ChildItem -Path "$SourceFolder"| Sort-Object LastAccessTime -Descending | Select-Object -First 1).Name
    $SrcPathD = $(Get-ChildItem -Path "$SourceFolder"| Sort-Object LastAccessTime -Descending | Select-Object -First 1).FullName

    Copy-Item -Path $SrcPathD -Destination $SrcDest -Recurse

    Sync-Files -Username $FTPUser -Password $FTPPass -Hostname $FTPHost -SrcPath "${CURRENT_DIR}\${SrcDest}" -DesPath "/site/wwwroot/pages/$SrcDest"

    Write-Host "Downloading coverage data file..."
    New-Item -Name "js" -ItemType directory
    Invoke-WebRequest -Uri "$Url" -OutFile "./js/pageData.js"

    #Parsing coverage
    Update-Coverage -SrcPath "${CURRENT_DIR}\js\pageData.js" -Htmlloc $SrcDest  -KernelName $KernelName
    Sync-Files -Username $FTPUser -Password $FTPPass -Hostname $FTPHost -SrcPath "${CURRENT_DIR}\js\pageData.js" -DesPath "/site/wwwroot/js/pageData.js"

    Write-Host "###Done####"
}

Main
