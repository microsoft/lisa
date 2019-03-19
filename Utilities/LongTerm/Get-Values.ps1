# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param (
    [String] $LogType,
    [String] $LogPath,
    [String] $CsvDest,
    [String] $LogDate
)

$PYTHON_PATH = "C:\Python27\python.exe"
$SCRIPT_PATH = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PARSER_PATH = Join-Path $SCRIPT_PATH "parser.ps1"
$CHECKER_PATH = Join-Path $SCRIPT_PATH "check_values.py"

if ( -not $LogDate) {
    $LogDate = Get-Date -UFormat "%Y-%m-%d"
}

$CHECK_VALUES = @{"iostat" = @{"DATE" = $LogDate; "Device" = "md0"};
                  "mpstat" = @{"DATE" = $LogDate; "CPU" = "all"};
                  "sar" = @{"DATE" = $LogDate; "IFACE" = "eth0"};
                  "sysbench" = @{"DATE" = $LogDate};
                  "vmstat" = @{"DATE" = $LogDate}}

$FINAL_COLUMNS = @{"iostat" = @("rkB/s", "wkB/s");
                   "mpstat" = @("sys", "iowait");
                   "sar" = @("rxkB/s", "txkB/s");
                   "sysbench" = @("reads", "writes");
                   "vmstat" = @("free", "in")}

function Main {
    # Parse the entire file
    $values = & $PARSER_PATH -LogType $LogType -LogPath $LogPath

    # Get the entries with the correct values
    if ($CHECK_VALUES[$LogType]) {
        $values = $values | ForEach-Object {
            $valuesMatch = $true
            foreach ($column in $CHECK_VALUES[$LogType].Keys) {
                if ($_[$column] -NotMatch $CHECK_VALUES[$LogType][$column]) {
                    $valuesMatch = $false
                }
            }
            if ($valuesMatch) {
                return $_
            }
        }
    }

    # Create the CSV
    $finalColumns = @()
    if ($FINAL_COLUMNS[$LogType]) {
        $finalColumns = $FINAL_COLUMNS[$LogType]
    }
    $values | ForEach-Object { New-Object psobject -Property $_ | Select-Object -Property $finalColumns | Export-Csv -Append $CsvDest}

    & $PYTHON_PATH $CHECKER_PATH --csv_path $CsvDest --check_columns "$([system.String]::Join(",", $finalColumns))" > parser.log

    Get-Content "parser.log" | Write-Host

    if ((Test-Path "failed_values.txt") -and (Get-Content "failed_values.txt")) {
        $failedColumns = Get-Content "failed_values.txt"
        Remove-Item "failed_values.txt"
        return $failedColumns
    }

    return $null
}

Main
