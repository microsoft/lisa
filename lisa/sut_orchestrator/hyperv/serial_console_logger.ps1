<#
.SYNOPSIS
    This script connects to a named pipe and logs the output to a file. This script is
    intended to be used with named pipes created using Set-VMCOMPort to get the serial
    console output of a VM.

.EXAMPLE
    .\serial_console_logger.ps1 -PipeName "\\.\pipe\mypipe" -OutFile "C:\temp\output.txt"

    This example connects to the named pipe "\\.\pipe\mypipe" and logs the output to
    "C:\temp\output.txt".

.NOTES
    Copyright (c) Microsoft Corporation.
    Licensed under the MIT license.
#>
param (
    [Parameter(Mandatory=$true)][string]$PipeName,
    [Parameter(Mandatory=$true)][string]$OutFile,
    [Parameter(Mandatory=$false)][int]$PipeConnectTimeoutMillis = 60000,
    [Parameter(Mandatory=$false)][int]$PipeReconnectTimeoutMillis = 15000
)

Write-Host "PID: $PID"
Write-Host "PipeName: $PipeName"
Write-Host "OutFile: $OutFile"

$oStream = New-Object System.IO.FileStream $OutFile, 'OpenOrCreate', 'Write', 'Read'
$pClient = New-Object System.IO.Pipes.NamedPipeClientStream(".", $PipeName)
$reconnect = $false
$maxConnectionAttempts = 10
$connectionAttempts = 0

try {
    while ($connectionAttempts -lt $maxConnectionAttempts) {
        $timeout = $PipeConnectTimeoutMillis
        if ($reconnect) {
            $timeout = $PipeReconnectTimeoutMillis
        }

        try {
            $connectionAttempts++
            Write-Host "Attempting to connect to pipe (attempt $connectionAttempts/$maxConnectionAttempts, timeout: $timeout ms)..."
            
            $pClient.Connect($timeout)
            
            if (!$pClient.IsConnected) {
                Write-Host "Failed to connect to pipe (not connected after timeout)"
                if ($connectionAttempts -ge $maxConnectionAttempts) {
                    Write-Host "Max connection attempts ($maxConnectionAttempts) reached. Exiting..."
                    exit 1
                }
                Write-Host "Waiting 5 seconds before retry..."
                $pClient.Dispose()
                $pClient = New-Object System.IO.Pipes.NamedPipeClientStream(".", $PipeName)
                Start-Sleep -Seconds 5
                continue
            }

            Write-Host "Connected to pipe"
            $connectionAttempts = 0  # Reset counter on successful connection
            
            $pClient.CopyTo($oStream)

            Write-Host "Disconnected from pipe. Reconnecting..."
            $reconnect = $true
            $pClient.Dispose()
            $pClient = New-Object System.IO.Pipes.NamedPipeClientStream(".", $PipeName)
        }
        catch {
            Write-Host "Error during connection or copy: $_"
            if ($connectionAttempts -ge $maxConnectionAttempts) {
                Write-Host "Max connection attempts ($maxConnectionAttempts) reached after error. Exiting..."
                exit 1
            }
            Write-Host "Waiting 5 seconds before retry..."
            Start-Sleep -Seconds 5
            $pClient.Dispose()
            $pClient = New-Object System.IO.Pipes.NamedPipeClientStream(".", $PipeName)
        }
    }
} finally {
    Write-Host "Cleaning up: closing pipe and file stream"
    if ($oStream) { $oStream.Close() }
    if ($pClient) { $pClient.Dispose() }
}