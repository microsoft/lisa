# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

param(
    [string] $Operation,
    [string] $Data
)

$ErrorActionPreference = 'Stop'
$Root = 'C:\ProgramData\lisa-vmapplications'
$Owner = 'lisa-vmapplications'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Assert-True($Condition, [string] $Message) {
    if (-not $Condition) { throw $Message }
}

function Read-Json([string] $Path) {
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Write-Json([string] $Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 20 -Compress), $Utf8)
}

function Get-BootId {
    return (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('O')
}

function Assert-Owner($InputData) {
    $item = Get-Item -LiteralPath $Root -Force
    Assert-True (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Fixture root must not be a reparse point'
    $ownership = Read-Json (Join-Path $Root 'owner.json')
    Assert-True ($ownership.owner -eq $Owner -and $ownership.vm_id -eq $InputData.vm_id) 'Fixture ownership does not match this VM'
}

function Add-Event($EventData) {
    $line = ($EventData | ConvertTo-Json -Depth 20 -Compress) + "`n"
    $stream = [IO.File]::Open((Join-Path $Root 'events.jsonl'), [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $bytes = $Utf8.GetBytes($line)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
}

function Get-Sha256([string] $Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try {
            return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
        } finally { $algorithm.Dispose() }
    } finally { $stream.Dispose() }
}

function Get-HandlerStatus {
    $files = @(
        foreach ($publisher in @('Microsoft.CPlat.Core', 'Microsoft.CPlat.Core.Edp')) {
            $base = Join-Path 'C:\Packages\Plugins' "$publisher.VMApplicationManagerWindows"
            if (Test-Path -LiteralPath $base) {
                Get-ChildItem -LiteralPath $base -Directory | ForEach-Object {
                    $statusDirectory = Join-Path $_.FullName 'Status'
                    if (Test-Path -LiteralPath $statusDirectory) {
                        Get-ChildItem -LiteralPath $statusDirectory -Filter '*.status' -File
                    }
                }
            }
        }
    )
    if (-not $files.Count) { return $null }
    $latest = $files | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    $statuses = @(Get-Content -LiteralPath $latest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json)
    $message = $statuses[0].status.formattedMessage.message
    $jsonStart = $message.IndexOf('{')
    Assert-True ($jsonStart -ge 0) 'Handler status does not contain a JSON object'
    $status = $message.Substring($jsonStart) | ConvertFrom-Json
    $actions = @(
        foreach ($item in $status.ActionsPerformed) {
            $result = 'FAILED'
            if ($item.result -ceq 'SUCCESS') { $result = 'SUCCESS' }
            elseif ($item.result -match 'skipped') { $result = 'SKIPPED' }
            @{name = $item.package; version = $item.version; op = $item.operation; result = $result}
        }
    )
    return @{
        handler = 'VMApplicationManagerWindows'
        version = $latest.Directory.Parent.Name
        actions = $actions
        error = [bool]($status.Errors -or $status.CriticalError)
    }
}

function Invoke-Utility([string] $Action, $InputData) {
    if ($Action -eq 'configure') {
        if (-not (Test-Path -LiteralPath $Root)) {
            New-Item -ItemType Directory -Path $Root | Out-Null
            Write-Json (Join-Path $Root 'owner.json') @{owner = $Owner; vm_id = $InputData.vm_id}
        }
        Assert-Owner $InputData
        $sentinel = Join-Path $Root 'unrelated.txt'
        if (-not (Test-Path -LiteralPath $sentinel)) {
            [IO.File]::WriteAllText($sentinel, "LISA VMApplications unrelated file`n", $Utf8)
        }
        New-Item -ItemType Directory -Path (Join-Path $Root 'state') -Force | Out-Null
        Write-Json (Join-Path $Root 'control.json') $InputData
        return @{}
    }
    Assert-Owner $InputData
    if ($Action -eq 'cleanup') {
        Remove-Item -LiteralPath $Root -Recurse -Force
        return @{}
    }
    Assert-True ($Action -eq 'inspect') "Unknown utility operation: $Action"
    $events = @()
    $log = Join-Path $Root 'events.jsonl'
    if (Test-Path -LiteralPath $log) {
        $events = @(Get-Content -LiteralPath $log -Encoding UTF8 |
            Where-Object { $_ } |
            ForEach-Object { $_ | ConvertFrom-Json } |
            Where-Object { $_.run -eq $InputData.run })
    }
    $states = @{}
    Get-ChildItem -LiteralPath (Join-Path $Root 'state') -Filter '*.json' -File | ForEach-Object {
        $states[$_.BaseName] = Read-Json $_.FullName
    }
    $directories = @{}
    $present = @{}
    foreach ($eventData in $events) {
        if ($eventData.directory) {
            $directories[$eventData.app] = $eventData.directory
            $present[$eventData.app] = Test-Path -LiteralPath $eventData.directory
        }
    }
    $compactEvents = @($events | Select-Object -Property * -ExcludeProperty run,directory)
    return @{run = $InputData.run; events = $compactEvents; states = $states; boot = Get-BootId; status = Get-HandlerStatus; unrelated = Get-Sha256 (Join-Path $Root 'unrelated.txt'); directories = $directories; present = $present}
}

function Invoke-Application([string] $Action, $InputData) {
    $control = Read-Json (Join-Path $Root 'control.json')
    Assert-Owner $control
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    Assert-True ($identity.User.Value -eq 'S-1-5-18') 'Application command must run as LocalSystem'
    $directory = (Get-Location).Path
    Assert-True ((Split-Path $directory -Leaf) -eq $InputData.version) "Unexpected version directory: $directory"
    Assert-True ((Split-Path (Split-Path $directory -Parent) -Leaf) -eq $InputData.name) "Unexpected application directory: $directory"
    $alias = $InputData.app
    $state = Join-Path $Root "state\$alias.json"
    $eventData = @{
        run = $control.run
        app = $alias
        op = $Action
        version = $InputData.version
        directory = $directory
        result = 'success'
    }
    if ($Action -in @('install', 'update')) {
        $package = Join-Path $directory $InputData.package
        Assert-True ((Get-Sha256 $package) -eq $InputData.sha256) 'Downloaded package bytes do not match'
        $expected = $InputData.config_sha256
        if ($control.configuration -and $control.configuration.PSObject.Properties[$alias]) {
            $expected = $control.configuration.$alias
        }
        $configuration = Join-Path $directory $InputData.config
        if ($null -eq $expected) {
            Assert-True (-not (Test-Path -LiteralPath $configuration)) 'Unexpected configuration file'
        } else {
            Assert-True ((Get-Sha256 $configuration) -eq $expected) 'Downloaded configuration bytes do not match'
        }
        foreach ($required in $control.requires.$alias) {
            Assert-True (Test-Path -LiteralPath (Join-Path $Root "state\$required.json")) "Required application is not installed: $required"
        }
    }
    if ($Action -eq 'action') {
        $eventData.action = $InputData.action
        $parameters = @{}
        foreach ($name in @('LISA_REQUIRED', 'LISA_OPTIONAL')) {
            $parameters[$name] = [Environment]::GetEnvironmentVariable($name)
            Assert-True ($parameters[$name] -ceq $control.parameters.$name) "Parameter value differs: $name"
        }
        $eventData.parameters = $parameters
    }
    $failed = $control.failures."$alias.$Action"
    if ($failed -or ($Action -eq 'action' -and $InputData.action -eq 'fail')) {
        $eventData.result = 'failed'
        Add-Event $eventData
        throw "LISA intentional failure: $alias.$Action"
    }
    $reboot = $control.reboot.$alias -eq $Action
    $rebootMarker = Join-Path $Root "reboot-$alias-$Action-$($InputData.version)"
    if ($reboot -and -not (Test-Path -LiteralPath $rebootMarker)) {
        [IO.File]::WriteAllText($rebootMarker, (Get-BootId), $Utf8)
        $eventData.result = 'reboot'
        Add-Event $eventData
        & shutdown.exe /r /t 2 /f
        Assert-True ($LASTEXITCODE -eq 0) 'Could not schedule reboot'
        Start-Sleep -Seconds 180
        throw 'The requested reboot did not terminate the command'
    }
    if ($Action -in @('install', 'update')) {
        Write-Json $state @{version = $InputData.version; run = $control.run}
        if ($alias -in $control.mutate) {
            $package = Join-Path $directory $InputData.package
            $bytes = [IO.File]::ReadAllBytes($package)
            $bytes[$bytes.Length - 1] = $bytes[$bytes.Length - 1] -bxor 1
            [IO.File]::WriteAllBytes($package, $bytes)
            if ($null -ne $InputData.config_sha256) {
                [IO.File]::AppendAllText((Join-Path $directory $InputData.config), 'x', $Utf8)
            }
        }
    } elseif ($Action -eq 'remove') {
        if (Test-Path -LiteralPath $state) { Remove-Item -LiteralPath $state }
    } else {
        Assert-True ($Action -eq 'action') "Unknown application operation: $Action"
    }
    Add-Event $eventData
}

if ($Operation) {
    $inputData = $Utf8.GetString([Convert]::FromBase64String($Data)) | ConvertFrom-Json
    if ($Operation -in @('configure', 'inspect', 'cleanup')) {
        $result = Invoke-Utility $Operation $inputData
        Write-Output ($inputData.marker + ($result | ConvertTo-Json -Depth 20 -Compress))
    } else {
        Invoke-Application $Operation $inputData
    }
}
