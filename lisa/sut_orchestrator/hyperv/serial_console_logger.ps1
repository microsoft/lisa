# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

param (
    [Parameter(Mandatory=$true)][string]$PipeName,
    [Parameter(Mandatory=$true)][string]$OutFile,
    [Parameter(Mandatory=$false)][int]$PipeReconnectMillis = 12000
)

Write-Host "PID: $PID"
Write-Host "PipeName: $PipeName"
Write-Host "OutFile: $OutFile"

$oStream = New-Object System.IO.FileStream $OutFile, 'OpenOrCreate', 'Write', 'Read'
$pClient = New-Object System.IO.Pipes.NamedPipeClientStream(".", $PipeName)
$reconnect = $false

try {
    while (1) {
        $timeout = 60000
        if ($reconnect) {
            $timeout = $PipeReconnectMillis
        }

        $pClient.Connect($timeout)
        if (!$pClient.IsConnected) {
            Write-Host "Failed to connect to pipe. Exiting..."
            exit
        }

        Write-Host "Connected to pipe"
        $pClient.CopyTo($oStream)

        Write-Host "Disconnected from pipe. Reconnecting..."
        $reconnect = $true
    }
} finally {
    Write-Host "Cleaning up: closing pipe and file stream"
    $oStream.Close()
    $pClient.Dispose()
}