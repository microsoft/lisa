# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param (
    [string] $ConfigPath,
    [string] $LogDestination,
    [string] $ReportDestination
)

$SCRIPT_PATH = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PARSER_PATH = Join-Path $SCRIPT_PATH "Get-Values.ps1"

$SERVER_LOGS = @{"iostat" = "iostat.log"; "sar" = "sar_server.log";
                 "mpstat" = "mpstat_server.log"; "sysbench" = "sysbench_run.log";
                 "vmstat" = "vmstat_server.log"}
$CLIENT_LOGS = @{"mpstat" = "mpstat_client.log"; "sar" = "sar_client.log";
                 "vmstat" = "vmstat_client.log"}

function Get-DataFromConfig {
    param (
        [string] $ConfigPath
    )
    # Expected config layout
    # SERVER_IP={ip}
    # SERVER_PORT={port}
    # CLIENT_IP={ip}
    # CLIENT_PORT={port}
    # REMOTE_LOG_PATH={vmLogPath}
    # VM_USERNAME={vmUser}
    # VM_PASSWORD={vmPass}

    $vmData = @{}
    $content = Get-Content $ConfigPath

    foreach ($line in $content) {
        $key = $line.split("=")[0]
        $value = $line.split("=")[1]

        $vmData[$key] = $value
    }

    return $vmData
}

function Download-Log {
    param (
        [string] $vmIP,
        [string] $vmPort,
        [string] $vmUsername,
        [string] $vmPassword,
        [string] $remotePath,
        [string] $destination
    )

    echo 'y' | & "$($env:ProgramFiles)\PuTTY\pscp.exe" -P $vmPort -pw $vmPassword root@${vmIP}:${remotePath} $destination
    if (Test-Path $destination) {
        return $true
    }
    return $false
}

function Main {
    if (-not (Test-Path $ConfigPath)) {
        throw "Cannot find config in path: $ConfigPath"
    }
    if (-not (Test-Path $LogDestination)) {
        throw "Cannot find log destination, path: $LogDestination"
    }

    # Create log path on current month / day
    $Date = Get-Date -UFormat "%Y-%m-%d"
    $monthlyLogDir = Join-Path $LogDestination (Get-Date -UFormat "%Y-%m")
    if (-not (Test-Path $monthlyLogDir)) {
        New-Item -Type Directory -Path $monthlyLogDir
    }
    $dailyLogDir = Join-Path $monthlyLogDir (Get-Date -UFormat "%d")
    if (Test-Path $dailyLogDir) {
        Remove-Item -Recurse -Force -Path $dailyLogDir
    }
    New-Item -Type Directory -Path $dailyLogDir

    $vmData = Get-DataFromConfig -ConfigPath $ConfigPath

    $checkResult = 0

    # Check server logs
    foreach ($logType in $SERVER_LOGS.Keys) {
        $logName = $SERVER_LOGS[$logType]
        $result = Download-Log -vmIP $vmData["SERVER_IP"] -vmPort $vmData["SERVER_PORT"] -vmUsername $vmData["VM_USERNAME"] `
            -vmPassword $vmData["VM_PASSWORD"] -remotePath "$($vmData['REMOTE_LOG_PATH'])/$($SERVER_LOGS[$logType])" `
            -destination $logName
        if ($result -eq $true) {
            Write-Host "Log: $($SERVER_LOGS[$logType]) downloaded successfully"
        }

        $csvName = "$($logName.Split(".")[0]).csv"

        $failedColumns = & $PARSER_PATH -LogType $logType -LogPath $logName -CsvDest $csvName -LogDate $Date
        if (-not (Test-Path $csvName)) {
            throw "Could not parse log: $logName"
        }

        Move-Item -Path @($logName, $csvName) -Destination $dailyLogDir

        $csvDest = Join-Path $dailyLogDir $csvName
        if ($failedColumns) {
            Write-Output "`nServer tool: $logType found out of range values" >> $ReportDestination
            Write-Output "CSV path: $csvDest" >> $ReportDestination
            if (Test-Path "parser.log") {
                Get-Content "parser.log" >> $ReportDestination
            }
            $checkResult = 1
        }
    }

    foreach ($logType in $CLIENT_LOGS.Keys) {
        $logName = $CLIENT_LOGS[$logType]
        $result = Download-Log -vmIP $vmData["CLIENT_IP"] -vmPort $vmData["CLIENT_PORT"] -vmUsername $vmData["VM_USERNAME"] `
            -vmPassword $vmData["VM_PASSWORD"] -remotePath "$($vmData['REMOTE_LOG_PATH'])/$($CLIENT_LOGS[$logType])" `
            -destination $logName
        if ($result -eq $true) {
            Write-Host "Log: $($CLIENT_LOGS[$logType]) downloaded successfully"
        }

        $csvName = "$($logName.Split(".")[0]).csv"

        $failedColumns = & $PARSER_PATH -LogType $logType -LogPath $logName -CsvDest $csvName -LogDate $Date
        if (-not (Test-Path $csvName)) {
            throw "Could not parse log: $logName"
        }

        Move-Item -Path @($logName, $csvName) -Destination $dailyLogDir

        $csvDest = Join-Path $dailyLogDir $csvName
        if ($failedColumns) {
            Write-Output "`nClient tool: $logType found out of range values" >> $ReportDestination
            Write-Output "CSV path: $csvDest" >> $ReportDestination
            if (Test-Path "parser.log") {
                Get-Content "parser.log" >> $ReportDestination
            }
            $checkResult = 1
        }
    }

    exit $checkResult
}

Main
